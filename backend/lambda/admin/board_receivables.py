"""Executive Board ``finance`` tools: listing receivables on siutindei Aurora.

Tables and views: ``scripts/siutindei/receivables.sql`` (apply in the product
repo). Mirror + dunning run from EventBridge Scheduler. The board never
initiates a bank payment.

Plan: docs/architecture/executive-board-tools-plan.md §5.4–§5.5.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from typing import Any

import board_data_api
import board_invoice_pdf
import board_mail
import board_meta
import board_store
import runtime
from board_data_api import Date, Numeric, Uuid
from contract_constants import BOARD_INVOICE_NUMBER_PREFIX, BOARD_RECEIVABLES_LIST_MAX
from finance_store import (
    _finance_owner_ddb_key,
    _load_finance_owner,
    _normalize_finance_payload,
)
from ddb_convert import _to_ddb_nested
from http_common import _log_event

BOOK = "siuTinDei"
DUNNING_OFFSETS = (7, 21, 35)
LINE_SOURCE = "receivables"
LINE_ID_PREFIXES = ("recv-inv-", "recv-pay-")
DSO_WINDOW_DAYS = 90
INVOICE_NUMBER_ATTEMPTS = 3
# Fixed approximation for USD→HKD (the HKD peg band is 7.75–7.85). The Lambda
# has no FX helper; unit economics only needs the order of magnitude.
USD_HKD = 7.8

OPEN_INVOICE_STATUSES = ("sent", "overdue")
SENDABLE_STATUSES = ("draft", "sent")
REMINDABLE_STATUSES = ("sent", "overdue")
UNMATCHABLE_STATUSES = ("paid", "void")
AMOUNT_TOLERANCE_HKD = 0.01


class ReceivablesError(RuntimeError):
    """User-facing receivables failure."""


def configured() -> bool:
    return board_data_api.configured() or board_data_api._executor is not None


def status_summary() -> dict[str, Any]:
    return {
        "configured": configured(),
        "clusterSet": bool(board_data_api.cluster_arn()),
    }


def _q(sql: str, **kwargs: Any) -> list[dict[str, Any]]:
    try:
        return board_data_api.execute(sql, board_data_api.params(**kwargs) if kwargs else None)
    except board_data_api.DataApiError as exc:
        raise ReceivablesError(str(exc)) from exc


def _one(sql: str, **kwargs: Any) -> dict[str, Any] | None:
    rows = _q(sql, **kwargs)
    return rows[0] if rows else None


def op_list_subscriptions(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "").strip()
    sql = (
        "SELECT s.id, s.organization_id, s.store_id, s.plan_id, s.starts_on, s.renews_on, "
        "s.status, s.payer_contact, p.name AS plan_name, p.price_hkd, p.billing_period "
        "FROM listing_subscriptions s LEFT JOIN listing_plans p ON p.id = s.plan_id "
    )
    if status:
        sql += "WHERE s.status = :status "
        rows = _q(sql + "ORDER BY s.renews_on NULLS LAST LIMIT :lim", status=status, lim=BOARD_RECEIVABLES_LIST_MAX)
    else:
        rows = _q(sql + "ORDER BY s.renews_on NULLS LAST LIMIT :lim", lim=BOARD_RECEIVABLES_LIST_MAX)
    return {"subscriptions": rows, "count": len(rows)}


def op_list_invoices(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "").strip()
    sql = (
        "SELECT id, subscription_id, number, issued_on, due_on, amount_hkd, status, "
        "fps_reference, pdf_key FROM invoices "
    )
    if status:
        rows = _q(sql + "WHERE status = :status ORDER BY due_on NULLS LAST LIMIT :lim", status=status, lim=BOARD_RECEIVABLES_LIST_MAX)
    else:
        rows = _q(sql + "ORDER BY due_on NULLS LAST LIMIT :lim", lim=BOARD_RECEIVABLES_LIST_MAX)
    return {"invoices": rows, "count": len(rows)}


def _days_overdue(due_on: Any, today: date) -> int:
    try:
        return (today - date.fromisoformat(str(due_on or today.isoformat())[:10])).days
    except ValueError:
        return 0


def _paid_revenue_since(since: date) -> float:
    row = _one(
        "SELECT COALESCE(SUM(amount_hkd), 0) AS total FROM invoices "
        "WHERE status = 'paid' AND issued_on >= :since",
        since=Date(since),
    ) or {}
    return float(row.get("total") or 0)


def _past_due_by_provider(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group past-due invoices by the subscription's organisation."""
    groups: dict[str, dict[str, Any]] = {}
    for inv in items:
        days = int(inv.get("daysOverdue") or 0)
        if days <= 0:
            continue
        org = str(inv.get("organization_id") or "") or f"subscription:{inv.get('subscription_id') or 'unknown'}"
        group = groups.setdefault(
            org,
            {
                "organizationId": str(inv.get("organization_id") or ""),
                "payerContact": str(inv.get("payer_contact") or ""),
                "subscriptionIds": [],
                "invoiceNumbers": [],
                "invoiceCount": 0,
                "amountHkd": 0.0,
                "oldestDaysOverdue": 0,
            },
        )
        sub_id = str(inv.get("subscription_id") or "")
        if sub_id and sub_id not in group["subscriptionIds"]:
            group["subscriptionIds"].append(sub_id)
        group["invoiceNumbers"].append(str(inv.get("number") or ""))
        group["invoiceCount"] += 1
        group["amountHkd"] = round(group["amountHkd"] + float(inv.get("amount_hkd") or 0), 2)
        group["oldestDaysOverdue"] = max(group["oldestDaysOverdue"], days)
    return sorted(groups.values(), key=lambda g: (-g["oldestDaysOverdue"], -g["amountHkd"]))


def op_aging_report(_ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    today_d = date.today()
    today = today_d.isoformat()
    rows = _q(
        "SELECT i.id, i.number, i.amount_hkd, i.status, i.due_on, i.fps_reference, "
        "i.subscription_id, s.organization_id, s.payer_contact "
        "FROM invoices i LEFT JOIN listing_subscriptions s ON s.id = i.subscription_id "
        "WHERE i.status IN ('sent', 'overdue') ORDER BY i.due_on"
    )
    buckets: dict[str, list[dict[str, Any]]] = {"current": [], "d7": [], "d21": [], "d35": []}
    outstanding = 0.0
    items: list[dict[str, Any]] = []
    for inv in rows:
        days = _days_overdue(inv.get("due_on"), today_d)
        amount = float(inv.get("amount_hkd") or 0)
        outstanding += amount
        item = {**inv, "daysOverdue": max(0, days)}
        items.append(item)
        if days < 7:
            buckets["current"].append(item)
        elif days < 21:
            buckets["d7"].append(item)
        elif days < 35:
            buckets["d21"].append(item)
        else:
            buckets["d35"].append(item)
    # DSO = outstanding receivables ÷ average daily paid revenue over the
    # trailing window; 0 when nothing was paid in the window.
    trailing = _paid_revenue_since(today_d - timedelta(days=DSO_WINDOW_DAYS))
    daily_revenue = trailing / DSO_WINDOW_DAYS
    dso = round(outstanding / daily_revenue, 1) if daily_revenue > 0 else 0.0
    return {
        "asOf": today,
        "outstandingHkd": round(outstanding, 2),
        "dso": dso,
        "dsoBasis": {"windowDays": DSO_WINDOW_DAYS, "paidRevenueHkd": round(trailing, 2)},
        "buckets": buckets,
        "pastDueByProvider": _past_due_by_provider(items),
    }


def _new_active_subscriptions(month_start: date) -> int:
    row = _one(
        "SELECT COUNT(*) AS n FROM listing_subscriptions "
        "WHERE status IN ('trial', 'active') AND starts_on >= :since",
        since=Date(month_start),
    ) or {}
    return int(row.get("n") or 0)


def op_unit_economics(_ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    paid = _one("SELECT COALESCE(SUM(amount_hkd), 0) AS total FROM invoices WHERE status = 'paid'") or {}
    active = _one("SELECT COUNT(*) AS n FROM listing_subscriptions WHERE status IN ('trial', 'active')") or {}
    month_start = date.today().replace(day=1)
    revenue_month = _paid_revenue_since(month_start)
    new_subs = _new_active_subscriptions(month_start)
    aws = board_store.get_cache(_ctx.table, "aws:monthly_cost") if _ctx is not None else None
    cost = 0.0
    if aws and isinstance(aws.get("payload"), dict):
        try:
            cost = float(aws["payload"].get("totalUsd") or 0)
        except (TypeError, ValueError):
            cost = 0.0
    snapshot: dict[str, Any] = (
        board_meta.ads_spend_snapshot(getattr(_ctx, "table", None), getattr(_ctx, "settings", None))
        if _ctx is not None
        else {"graphMonthlyUsd": 0.0, "recordedMonthlyUsd": 0.0, "graphCurrency": "", "graphAvailable": False}
    )
    recorded = float(snapshot.get("recordedMonthlyUsd") or 0)
    graph_spend = float(snapshot.get("graphMonthlyUsd") or 0)
    currency = str(snapshot.get("graphCurrency") or "USD").upper()
    # Graph is what Meta actually billed; recorded commitments are the board's
    # own approvals this month. They overlap once an ad delivers, so take the
    # larger rather than the sum.
    meta_cost = max(graph_spend, recorded)
    meta_source = "graph" if graph_spend >= recorded and snapshot.get("graphAvailable") else "recorded"
    revenue = float(paid.get("total") or 0)
    providers = int(active.get("n") or 0)
    out: dict[str, Any] = {
        "paidInvoicesHkd": revenue,
        "activeSubscriptions": providers,
        "revenuePerSubscriptionHkd": round(revenue / max(providers, 1), 2),
        "awsMonthlyUsd": cost,
        "metaAdsMonthly": meta_cost,
        "metaAdsCurrency": currency if meta_source == "graph" else "USD",
        "metaAdsSource": meta_source,
        "metaAdsRecordedMonthlyUsd": recorded,
        "metaAdsGraphMonthly": graph_spend,
        "metaAdsGraphCurrency": currency,
        "note": "Meta ads cost is the larger of Graph month-to-date and the board's recorded commitments (they overlap).",
    }
    meta_usd: float | None
    if meta_source == "recorded" or (meta_source == "graph" and currency == "USD"):
        meta_usd = meta_cost
        out["metaAdsMonthlyUsd"] = meta_cost
    else:
        meta_usd = None
        out["note"] += f" Graph reports the ad account in {currency}; convert before comparing with USD figures."
    # Acquisition cost and margin are month-to-date: AWS + Meta (when in USD)
    # against subscriptions that started this month and invoices paid this month.
    monthly_cost_usd = cost + (meta_usd or 0.0)
    cost_hkd = round(monthly_cost_usd * USD_HKD, 2)
    out.update(
        {
            "newActiveSubscriptions": new_subs,
            "cpaUsd": round(monthly_cost_usd / new_subs, 2) if new_subs > 0 else None,
            "revenueMonthHkd": round(revenue_month, 2),
            "costMonthHkd": cost_hkd,
            "grossMarginPct": round((revenue_month - cost_hkd) / revenue_month * 100, 1) if revenue_month > 0 else None,
            "usdHkdRate": USD_HKD,
            "monthStart": month_start.isoformat(),
        }
    )
    out["note"] += (
        f" cpaUsd and grossMarginPct are month-to-date; USD costs are converted at a fixed {USD_HKD} HKD/USD approximation."
        + (" Meta spend is excluded from cpaUsd because it is not in USD." if meta_usd is None and meta_cost > 0 else "")
    )
    return out


def _next_number() -> str:
    year = date.today().year
    prefix = f"{BOARD_INVOICE_NUMBER_PREFIX}-{year}-"
    row = _one("SELECT number FROM invoices WHERE number LIKE :p ORDER BY number DESC LIMIT 1", p=f"{prefix}%")
    seq = 1
    if row and str(row.get("number") or "").startswith(prefix):
        try:
            seq = int(str(row["number"])[len(prefix):]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:04d}"


def _fps_ref() -> str:
    return f"{BOARD_INVOICE_NUMBER_PREFIX}{uuid.uuid4().hex[:8].upper()}"


def _insert_invoice(*, inv_id: str, sub_id: str, issued: date, due: date, amount_hkd: float) -> tuple[str, str]:
    """Insert a draft invoice, recomputing the number on a unique violation.

    Two personas drafting at the same moment both read the same "last number";
    ``invoices.number`` is UNIQUE, so the loser retries with the next one.
    """
    fps = _fps_ref()
    for attempt in range(1, INVOICE_NUMBER_ATTEMPTS + 1):
        number = _next_number()
        try:
            _q(
                "INSERT INTO invoices (id, subscription_id, number, issued_on, due_on, amount_hkd, status, fps_reference) "
                "VALUES (:id, :sub, :number, :issued, :due, :amount, 'draft', :fps)",
                id=Uuid(inv_id),
                sub=Uuid(sub_id),
                number=number,
                issued=Date(issued),
                due=Date(due),
                amount=Numeric(amount_hkd),
                fps=fps,
            )
            return number, fps
        except ReceivablesError as exc:
            if not board_data_api.is_unique_violation(exc) or attempt >= INVOICE_NUMBER_ATTEMPTS:
                raise
            _log_event("warning", tag="board_invoice_number_retry", number=number, attempt=attempt)
            fps = _fps_ref()
    raise ReceivablesError("could not allocate a unique invoice number")  # pragma: no cover - loop returns or raises


def op_draft_invoice(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    sub_id = str(args.get("subscriptionId") or "").strip()
    amount = args.get("amountHkd")
    try:
        hkd = float(amount)
    except (TypeError, ValueError) as exc:
        raise ReceivablesError("amountHkd must be a number") from exc
    if hkd <= 0:
        raise ReceivablesError("amountHkd must be positive")
    sub = _one("SELECT id, payer_contact FROM listing_subscriptions WHERE id = :id", id=Uuid(sub_id))
    if not sub:
        raise ReceivablesError(f"subscription {sub_id} not found")
    due_days = int(args.get("dueInDays") or 14)
    issued = date.today()
    due = issued + timedelta(days=max(1, min(due_days, 90)))
    inv_id = str(uuid.uuid4())
    number, fps = _insert_invoice(inv_id=inv_id, sub_id=sub_id, issued=issued, due=due, amount_hkd=hkd)
    pdf_key, pdf_notes = _store_invoice_pdf(
        invoice_id=inv_id,
        number=number,
        amount_hkd=hkd,
        fps_reference=fps,
        issued_on=issued.isoformat(),
        due_on=due.isoformat(),
        payer_contact=str(sub.get("payer_contact") or ""),
    )
    if pdf_key:
        _q("UPDATE invoices SET pdf_key = :key WHERE id = :id", key=pdf_key, id=Uuid(inv_id))
    out = {
        "ok": True,
        "invoiceId": inv_id,
        "number": number,
        "fpsReference": fps,
        "amountHkd": hkd,
        "dueOn": due.isoformat(),
        "status": "draft",
        "payerContact": sub.get("payer_contact"),
        "pdfKey": pdf_key,
    }
    if pdf_notes:
        out["pdfWarning"] = " ".join(pdf_notes)
    return out


def _store_invoice_pdf(
    *,
    invoice_id: str,
    number: str,
    amount_hkd: float,
    fps_reference: str,
    issued_on: str,
    due_on: str,
    payer_contact: str,
) -> tuple[str, tuple[str, ...]]:
    """Render and upload the invoice PDF. Returns ``(s3 key or "", notes)``.

    A failed upload never fails the draft: the ledger row is the source of
    truth and the owner is told through ``pdfWarning`` instead.
    """
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not bucket:
        return "", ("PDF not stored: no assets bucket is configured.",)
    rendered = board_invoice_pdf.render_invoice(
        number=number,
        amount_hkd=amount_hkd,
        fps_reference=fps_reference,
        issued_on=issued_on,
        due_on=due_on,
        payer_contact=payer_contact,
    )
    key = board_invoice_pdf.invoice_s3_key(invoice_id, issued_on)
    try:
        runtime._s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=rendered.data,
            ContentType="application/pdf",
        )
    except Exception as exc:
        _log_event("warning", tag="board_invoice_pdf_failed", invoiceId=invoice_id, error=str(exc)[:200])
        return "", (*rendered.notes, "PDF could not be stored; send the invoice without an attachment or re-draft.")
    return key, rendered.notes


def _load_invoice_pdf(inv: dict[str, Any]) -> bytes | None:
    key = str(inv.get("pdf_key") or "").strip()
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not key or not bucket:
        return None
    try:
        obj = runtime._s3.get_object(Bucket=bucket, Key=key)
        body = obj.get("Body")
        data = body.read() if hasattr(body, "read") else body
    except Exception as exc:
        _log_event("warning", tag="board_invoice_pdf_load_failed", key=key, error=str(exc)[:200])
        return None
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    _log_event("warning", tag="board_invoice_pdf_load_failed", key=key, error="object body was not bytes")
    return None


def _invoice_pdf_available(inv: dict[str, Any]) -> bool:
    key = str(inv.get("pdf_key") or "").strip()
    bucket = (os.environ.get("ASSETS_BUCKET_NAME") or "").strip()
    if not key or not bucket:
        return False
    try:
        runtime._s3.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        _log_event("warning", tag="board_invoice_pdf_missing", key=key, error=str(exc)[:200])
        return False
    return True


def _invoice(invoice_id: str) -> dict[str, Any]:
    if not invoice_id:
        raise ReceivablesError("invoiceId is required")
    inv = _one("SELECT * FROM invoices WHERE id = :id", id=Uuid(invoice_id))
    if not inv:
        raise ReceivablesError(f"invoice {invoice_id} not found")
    return inv


def _require_status(inv: dict[str, Any], allowed: tuple[str, ...], *, action: str) -> None:
    status = str(inv.get("status") or "")
    if status not in allowed:
        raise ReceivablesError(
            f"invoice {inv.get('number') or inv.get('id')} is {status or 'unknown'}; "
            f"only {' or '.join(allowed)} invoices can be {action}"
        )


def _transition_reason(inv: dict[str, Any], allowed: tuple[str, ...], *, action: str) -> str | None:
    try:
        _require_status(inv, allowed, action=action)
    except ReceivablesError as exc:
        return str(exc)
    return None


def payer_email(invoice: dict[str, Any]) -> str:
    sub_id = invoice.get("subscription_id")
    if not sub_id:
        return ""
    sub = _one("SELECT payer_contact FROM listing_subscriptions WHERE id = :id", id=Uuid(sub_id))
    return str((sub or {}).get("payer_contact") or "")


def act_guard_send(_ctx: Any, args: dict[str, Any], *, op: str) -> str | None:
    inv = _invoice(str(args.get("invoiceId") or ""))
    if op == "finance_send_reminder":
        blocked = _transition_reason(inv, REMINDABLE_STATUSES, action="reminded")
    else:
        blocked = _transition_reason(inv, SENDABLE_STATUSES, action="sent")
    if blocked:
        return blocked
    email = payer_email(inv)
    if not email:
        return "the subscription has no payer contact"
    if not board_mail.recipient_allowed(getattr(_ctx, "settings", {}) or {}, email):
        return f"{email} is not on the email allow-list"
    return None


def owner_preview_send(_ctx: Any, args: dict[str, Any], *, op: str) -> dict[str, Any]:
    inv = _invoice(str(args.get("invoiceId") or ""))
    email = payer_email(inv)
    kind = "reminder" if op == "finance_send_reminder" else "invoice"
    label = "Reminder" if kind == "reminder" else "Invoice"
    note = str(args.get("note") or args.get("reason") or "").strip()
    body = (
        f"{label} {inv.get('number')} for HK${inv.get('amount_hkd')}. "
        f"Pay by FPS quoting {inv.get('fps_reference')}. Due {inv.get('due_on')}."
    )
    if note:
        body = f"{body}\n\n{note}"
    has_pdf = _invoice_pdf_available(inv)
    preview = {
        "kind": "email",
        "from": "billing@siutindei.com",
        "to": [email] if email else [],
        "cc": [],
        "subject": f"{label} {inv.get('number')} — HK${inv.get('amount_hkd')} (FPS {inv.get('fps_reference')})",
        "text": body,
        "threadId": "",
        "sendEnabled": board_mail.sending_enabled(),
        "invoiceId": inv.get("id"),
        "number": inv.get("number"),
        "fpsReference": inv.get("fps_reference"),
        "amountHkd": inv.get("amount_hkd"),
        "pdfKey": inv.get("pdf_key") or "",
        "attachments": [{"name": f"{inv.get('number')}.pdf"}] if has_pdf else [],
    }
    if inv.get("pdf_key") and not has_pdf:
        preview["pdfWarning"] = "The invoice PDF is missing from storage; the email will go without an attachment."
    return preview


def _send_mail(ctx: Any, inv: dict[str, Any], *, subject: str, body: str) -> dict[str, Any]:
    email = payer_email(inv)
    if not email:
        raise ReceivablesError("subscription has no payer contact")
    if not board_mail.sending_enabled():
        _q("UPDATE invoices SET status = 'sent' WHERE id = :id AND status = 'draft'", id=Uuid(inv["id"]))
        return {"ok": True, "sent": False, "note": "Sending is off; invoice marked sent in the ledger only."}
    plan = board_mail.outgoing_plan(
        ctx.table,
        op="mail_send",
        args={
            "fromMailbox": "billing",
            "to": [email],
            "subject": subject,
            "body": body,
        },
    )
    pdf = _load_invoice_pdf(inv)
    if pdf:
        plan["attachments"] = [
            {"filename": f"{inv.get('number') or 'invoice'}.pdf", "contentType": "application/pdf", "content": pdf}
        ]
    result = board_mail.send_plan(ctx.table, plan, sent_by=getattr(ctx, "persona_id", "cfo"))
    if inv.get("pdf_key") and not pdf:
        result = {
            **result,
            "attachmentMissing": True,
            "warning": "The invoice PDF could not be loaded, so the email went without an attachment.",
        }
    return result


def _send_extras(result: dict[str, Any]) -> dict[str, Any]:
    """Carry send failures and attachment warnings into the tool result."""
    if not result.get("ok"):
        return dict(result)
    return {k: v for k, v in result.items() if k in ("attachmentMissing", "warning", "sent", "note")}


def op_send_invoice(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    inv = _invoice(str(args.get("invoiceId") or ""))
    _require_status(inv, SENDABLE_STATUSES, action="sent")
    subject = f"Invoice {inv['number']} — HK${inv['amount_hkd']} (FPS {inv.get('fps_reference')})"
    body = (
        f"Please pay HK${inv['amount_hkd']} by FPS quoting {inv.get('fps_reference')}. "
        f"Due {inv.get('due_on')}.\n\nThe siutindei team"
    )
    result = _send_mail(ctx, inv, subject=subject, body=body)
    _q("UPDATE invoices SET status = 'sent' WHERE id = :id AND status IN ('draft', 'sent')", id=Uuid(inv["id"]))
    return {"ok": True, "invoiceId": inv["id"], "number": inv["number"], **_send_extras(result)}


def op_send_reminder(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    inv = _invoice(str(args.get("invoiceId") or ""))
    _require_status(inv, REMINDABLE_STATUSES, action="reminded")
    subject = f"Reminder: invoice {inv['number']} is due (FPS {inv.get('fps_reference')})"
    body = (
        f"This is a reminder that invoice {inv['number']} for HK${inv['amount_hkd']} "
        f"was due {inv.get('due_on')}. Please pay by FPS quoting {inv.get('fps_reference')}.\n\nThe siutindei team"
    )
    result = _send_mail(ctx, inv, subject=subject, body=body)
    if str(inv.get("status")) == "sent":
        _q("UPDATE invoices SET status = 'overdue' WHERE id = :id AND status = 'sent'", id=Uuid(inv["id"]))
    out = {"ok": True, "invoiceId": inv["id"], "number": inv["number"], **_send_extras(result)}
    if args.get("stage"):
        out["stage"] = args.get("stage")
    return out


def _payment(payment_id: str) -> dict[str, Any]:
    if not payment_id:
        raise ReceivablesError("paymentId is required")
    pay = _one("SELECT * FROM payments WHERE id = :id", id=Uuid(payment_id))
    if not pay:
        raise ReceivablesError(f"payment {payment_id} not found")
    return pay


def _match_agreement(pay: dict[str, Any], inv: dict[str, Any]) -> tuple[bool, bool]:
    amount_ok = abs(float(pay.get("amount_hkd") or 0) - float(inv.get("amount_hkd") or 0)) < AMOUNT_TOLERANCE_HKD
    ref = str(pay.get("bank_reference") or "").strip().upper()
    ref_ok = bool(ref) and ref == str(inv.get("fps_reference") or "").strip().upper()
    return amount_ok, ref_ok


def _match_block_reason(pay: dict[str, Any], inv: dict[str, Any]) -> str | None:
    """Hard failures: the payment or invoice cannot take this match at all."""
    blocked = _transition_reason(inv, ("draft", *OPEN_INVOICE_STATUSES), action="matched")
    if blocked:
        return blocked
    attached = str(pay.get("invoice_id") or "")
    if attached and attached != str(inv.get("id")):
        return f"payment {pay.get('id')} is already attached to invoice {attached}"
    return None


def match_candidates(pay: dict[str, Any], *, exclude_invoice_id: str = "") -> list[dict[str, Any]]:
    """Open invoices whose amount (±0.01) or FPS reference matches the payment."""
    amount = float(pay.get("amount_hkd") or 0)
    ref = str(pay.get("bank_reference") or "").strip().upper()
    rows = _q(
        "SELECT id, number, amount_hkd, status, due_on, fps_reference, subscription_id FROM invoices "
        "WHERE status IN ('draft', 'sent', 'overdue') AND (ABS(amount_hkd - :amount) <= :tol OR UPPER(fps_reference) = :ref) "
        "ORDER BY due_on NULLS LAST LIMIT :lim",
        amount=Numeric(amount),
        tol=Numeric(AMOUNT_TOLERANCE_HKD),
        ref=ref or "-",
        lim=BOARD_RECEIVABLES_LIST_MAX,
    )
    out: list[dict[str, Any]] = []
    for inv in rows:
        if exclude_invoice_id and str(inv.get("id")) == exclude_invoice_id:
            continue
        amount_ok, ref_ok = _match_agreement(pay, inv)
        out.append({**inv, "amountAgrees": amount_ok, "referenceAgrees": ref_ok})
    return out


def _candidates_summary(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "no other open invoice matches the amount or reference"
    parts = [f"{c.get('number')} (HK${c.get('amount_hkd')}, {c.get('status')})" for c in candidates[:5]]
    return "candidates: " + ", ".join(parts)


def op_match_payment(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    pay_id = str(args.get("paymentId") or "").strip()
    inv_id = str(args.get("invoiceId") or "").strip()
    pay = _payment(pay_id)
    inv = _invoice(inv_id)
    blocked = _match_block_reason(pay, inv)
    if blocked:
        raise ReceivablesError(blocked)
    amount_ok, ref_ok = _match_agreement(pay, inv)
    _q(
        "UPDATE payments SET invoice_id = :inv, matched_by = :who WHERE id = :id",
        inv=Uuid(inv_id),
        who=str(args.get("matchedBy") or "board"),
        id=Uuid(pay_id),
    )
    if amount_ok:
        _q("UPDATE invoices SET status = 'paid' WHERE id = :id", id=Uuid(inv_id))
    out: dict[str, Any] = {
        "ok": True,
        "matched": True,
        "amountAgrees": amount_ok,
        "referenceAgrees": ref_ok,
        "invoiceId": inv_id,
        "paymentId": pay_id,
        "invoiceStatus": "paid" if amount_ok else str(inv.get("status") or ""),
    }
    if not (amount_ok and ref_ok):
        out["candidates"] = match_candidates(pay, exclude_invoice_id=inv_id)
        out["note"] = (
            "Attached on the founder's decision although amount and FPS reference did not both agree; "
            "the invoice stays open until a full-amount payment is matched."
            if not amount_ok
            else "Attached on the founder's decision; the FPS reference did not agree."
        )
    return out


def act_guard_match(_ctx: Any, args: dict[str, Any]) -> str | None:
    try:
        pay = _payment(str(args.get("paymentId") or ""))
        inv = _invoice(str(args.get("invoiceId") or ""))
    except ReceivablesError as exc:
        return str(exc)
    blocked = _match_block_reason(pay, inv)
    if blocked:
        return blocked
    amount_ok, ref_ok = _match_agreement(pay, inv)
    if amount_ok and ref_ok:
        return None
    candidates = match_candidates(pay, exclude_invoice_id=str(inv.get("id") or ""))
    return f"amount or FPS reference does not agree with the invoice; {_candidates_summary(candidates)}"


def op_propose_price_change(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    name = " ".join(str(args.get("name") or "").split())[:80]
    period = str(args.get("billingPeriod") or "monthly")
    if period not in ("monthly", "annual"):
        raise ReceivablesError("billingPeriod must be monthly or annual")
    try:
        price = float(args.get("priceHkd"))
    except (TypeError, ValueError) as exc:
        raise ReceivablesError("priceHkd must be a number") from exc
    if price <= 0:
        raise ReceivablesError("priceHkd must be positive")
    plan_id = str(uuid.uuid4())
    _q(
        "INSERT INTO listing_plans (id, name, price_hkd, billing_period, active) "
        "VALUES (:id, :name, :price, :period, true)",
        id=Uuid(plan_id),
        name=name,
        price=Numeric(price),
        period=period,
    )
    return {"ok": True, "planId": plan_id, "name": name, "priceHkd": price, "billingPeriod": period}


def op_record_manual_payment(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        amount = float(args.get("amountHkd"))
    except (TypeError, ValueError) as exc:
        raise ReceivablesError("amountHkd must be a number") from exc
    if amount <= 0:
        raise ReceivablesError("amountHkd must be positive")
    received = str(args.get("receivedOn") or date.today().isoformat())[:10]
    try:
        date.fromisoformat(received)
    except ValueError as exc:
        raise ReceivablesError("receivedOn must be YYYY-MM-DD") from exc
    pay_id = str(uuid.uuid4())
    inv_id = str(args.get("invoiceId") or "").strip() or None
    # The row is inserted unattached; ``op_match_payment`` attaches it so the
    # same status guards apply as for any other match.
    _q(
        "INSERT INTO payments (id, invoice_id, received_on, amount_hkd, payer_name, bank_reference, source, matched_by) "
        "VALUES (:id, :inv, :received, :amount, :payer, :ref, 'manual', :who)",
        id=Uuid(pay_id),
        inv=Uuid(None),
        received=Date(received),
        amount=Numeric(amount),
        payer=str(args.get("payerName") or "")[:120],
        ref=str(args.get("bankReference") or "")[:80],
        who="manual",
    )
    out: dict[str, Any] = {"ok": True, "paymentId": pay_id, "amountHkd": amount, "invoiceId": inv_id}
    if inv_id:
        try:
            matched = op_match_payment(_ctx, {"paymentId": pay_id, "invoiceId": inv_id, "matchedBy": "manual"})
        except ReceivablesError as exc:
            _log_event("warning", tag="board_manual_payment_unmatched", paymentId=pay_id, error=str(exc)[:200])
            out["matched"] = False
            out["matchWarning"] = str(exc)
        else:
            out["matched"] = True
            out["amountAgrees"] = matched.get("amountAgrees")
    return out


def aging_for_owner() -> dict[str, Any]:
    if not configured():
        return {"configured": False, "invoices": [], "subscriptions": [], "aging": {"buckets": {}, "outstandingHkd": 0}}
    return {
        "configured": True,
        "invoices": op_list_invoices(None, {})["invoices"],
        "subscriptions": op_list_subscriptions(None, {})["subscriptions"],
        "aging": op_aging_report(None, {}),
    }


def _line_same(prev: dict[str, Any], line: dict[str, Any]) -> bool:
    try:
        return (
            str(prev.get("description") or "") == str(line.get("description") or "")
            and str(prev.get("dateUtc") or "") == str(line.get("dateUtc") or "")
            and float(prev.get("grossAmount") or 0) == float(line.get("grossAmount") or 0)
            and str(prev.get("type") or "") == str(line.get("type") or "")
        )
    except (TypeError, ValueError):
        return False


def _is_mirrored_line(line: dict[str, Any]) -> bool:
    lid = str(line.get("id") or "")
    return lid.startswith(LINE_ID_PREFIXES) or str(line.get("source") or "") == LINE_SOURCE


def _upsert_book_lines(table: Any, desired: list[dict[str, Any]]) -> tuple[int, int]:
    """Replace the book's receivables lines with ``desired``.

    Lines the mirror wrote earlier that are no longer desired (an invoice
    that got paid, a payment that was detached) are removed so the book never
    shows a receivable next to the payment that settled it. Manually entered
    lines are never touched. Returns ``(written, removed)``.
    """
    data = _load_finance_owner(table, BOOK)
    existing = [ln for ln in (data.get("lines") or []) if isinstance(ln, dict)]
    desired_by_id = {str(ln["id"]): ln for ln in desired}
    kept: list[dict[str, Any]] = []
    written = 0
    removed = 0
    seen: set[str] = set()
    for prev in existing:
        lid = str(prev.get("id") or "")
        if not _is_mirrored_line(prev):
            kept.append(prev)
            continue
        line = desired_by_id.get(lid)
        if line is None:
            removed += 1
            continue
        seen.add(lid)
        if _line_same(prev, line) and str(prev.get("source") or "") == LINE_SOURCE:
            kept.append(prev)
        else:
            kept.append(line)
            written += 1
    for lid, line in desired_by_id.items():
        if lid not in seen:
            kept.append(line)
            written += 1
    if not written and not removed:
        return 0, 0
    payload = _normalize_finance_payload(
        {
            "defaultCurrency": data.get("defaultCurrency") or "HKD",
            "float": data.get("float") or {"amount": 0, "currency": "HKD"},
            "lines": kept,
        }
    )
    # Normalisation drops unknown keys; re-tag our lines so consumers can
    # tell mirrored rows from manual entries.
    for line in payload["lines"]:
        if str(line.get("id") or "").startswith(LINE_ID_PREFIXES):
            line["source"] = LINE_SOURCE
    table.put_item(Item={**_finance_owner_ddb_key(BOOK), **_to_ddb_nested(payload)})
    return written, removed


def _mirror_line(*, line_id: str, day: Any, description: str, amount: float) -> dict[str, Any]:
    iso = f"{str(day or date.today().isoformat())[:10]}T00:00:00.000Z"
    return {
        "id": line_id,
        "dateUtc": iso,
        "type": "income",
        "description": description,
        "netAmount": amount,
        "vat": 0,
        "grossAmount": amount,
        "currency": "HKD",
        "source": LINE_SOURCE,
    }


def desired_book_lines() -> list[dict[str, Any]]:
    """The complete set of lines the book should hold for receivables right now."""
    invoices = _q(
        "SELECT id, number, amount_hkd, status, issued_on, due_on FROM invoices WHERE status IN ('sent', 'overdue')"
    )
    payments = _q("SELECT id, invoice_id, amount_hkd, received_on FROM payments WHERE invoice_id IS NOT NULL")
    lines: list[dict[str, Any]] = []
    for inv in invoices:
        lines.append(
            _mirror_line(
                line_id=f"recv-inv-{inv['id']}",
                day=inv.get("issued_on"),
                description=f"[receivables] Invoice {inv.get('number')} due {inv.get('due_on')} ({inv.get('status')})",
                amount=float(inv.get("amount_hkd") or 0),
            )
        )
    for pay in payments:
        lines.append(
            _mirror_line(
                line_id=f"recv-pay-{pay['id']}",
                day=pay.get("received_on"),
                description=f"[receivables] Payment matched to invoice {pay.get('invoice_id')}",
                amount=float(pay.get("amount_hkd") or 0),
            )
        )
    return lines


def mirror_to_statement_book(table: Any) -> dict[str, Any]:
    """Outstanding invoices and matched payments → Siu Tin Dei book lines.

    Sent/overdue invoices become income rows (still receivable) and matched
    payments become income rows. Stable ``recv-inv-*`` / ``recv-pay-*`` ids,
    ``source=receivables`` and a ``[receivables]`` description prefix make
    re-runs idempotent; lines that fall out of the desired set are removed.
    """
    written, removed = _upsert_book_lines(table, desired_book_lines())
    _log_event("info", tag="board_receivables_mirrored", lines=written, removed=removed)
    return {"ok": True, "linesWritten": written, "linesRemoved": removed}


def handle_mirror_trigger(event: dict[str, Any]) -> dict[str, Any]:
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    if not configured():
        return {"ok": True, "skipped": "not_configured"}
    return mirror_to_statement_book(board_store.records_table())


def dunning_stage(days_overdue: int) -> str:
    return f"d{days_overdue}"


def _reminder_approvals(table: Any) -> list[dict[str, Any]]:
    return [a for a in board_store.list_approvals(table) if a.get("op") == "finance_send_reminder"]


def approval_stage(approval: dict[str, Any]) -> str:
    """The dunning stage an approval was queued for (``arguments.stage``; older rows used ``dunningStage``)."""
    args = approval.get("arguments") or {}
    return str(args.get("stage") or approval.get("dunningStage") or "")


def _already_queued(approvals: list[dict[str, Any]], invoice_id: str, stage: str) -> bool:
    """True when a reminder for this invoice+stage exists in any state, or one is still pending."""
    for a in approvals:
        args = a.get("arguments") or {}
        if str(args.get("invoiceId") or "") != invoice_id:
            continue
        if a.get("status") == "pending":
            return True
        if approval_stage(a) == stage:
            return True
    return False


def handle_dunning_trigger(event: dict[str, Any]) -> dict[str, Any]:
    """Queue propose-level reminder approvals on the exact D+7 / D+21 / D+35 days.

    Firing only on the exact day (rather than "≥ 7 days") means a daily
    schedule proposes each stage once without tracking state on the invoice;
    the approval log (any status) is the dedupe for re-runs on the same day.
    """
    if not board_store.event_targets_this_board(event):
        return {"ok": True, "skipped": "other_board"}
    if not configured():
        return {"ok": True, "skipped": "not_configured"}
    import board_tools

    table = board_store.records_table()
    settings = board_store.load_settings(table)
    aging = op_aging_report(None, {})
    approvals = _reminder_approvals(table)
    created = 0
    skipped = 0
    refused = 0
    for bucket in (aging.get("buckets") or {}).values():
        for inv in bucket:
            inv_id = str(inv.get("id") or "")
            days = int(inv.get("daysOverdue") or 0)
            if not inv_id or days not in DUNNING_OFFSETS:
                continue
            stage = dunning_stage(days)
            if _already_queued(approvals, inv_id, stage):
                skipped += 1
                continue
            ctx = board_tools.ToolContext(
                table=table,
                settings=settings,
                persona_id="cfo",
                display_name="CFO",
                kind="schedule",
            )
            try:
                doc = board_tools.create_approval(
                    ctx,
                    board_tools.REGISTRY["finance_send_reminder"],
                    {"invoiceId": inv_id, "stage": stage, "reason": f"Automatic dunning at D+{days} for {inv.get('number')}."},
                    summary=f"Dunning reminder (D+{days}) for {inv.get('number')}",
                )
            except board_tools.ToolPermissionError as exc:
                refused += 1
                _log_event("warning", tag="board_dunning_refused", invoiceId=inv_id, stage=stage, error=str(exc)[:200])
                continue
            approvals.append(doc)
            created += 1
    _log_event("info", tag="board_dunning_queued", created=created, skipped=skipped, refused=refused)
    return {"ok": True, "created": created, "skipped": skipped, "refused": refused}


def digest_for_context() -> dict[str, Any]:
    if not configured():
        return {}
    try:
        aging = op_aging_report(None, {})
    except ReceivablesError:
        return {}
    return {
        "outstandingHkd": aging.get("outstandingHkd"),
        "overdue": len((aging.get("buckets") or {}).get("d7") or [])
        + len((aging.get("buckets") or {}).get("d21") or [])
        + len((aging.get("buckets") or {}).get("d35") or []),
    }
