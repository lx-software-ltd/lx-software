"""T4: finance / product tools, Data API fake, statement-book mirror, dunning."""

from __future__ import annotations

import re
import unittest
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import board_context
import board_data_api
import board_product
import board_receivables
import board_store
import dispatch
from board_tools import REGISTRY, ToolContext, execute_call
from test_board import BoardTestCase
from test_board_tools import ToolsTestCase


def _unwrap(parameters: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Mimic what Postgres would hand back for each typed parameter.

    Wire format is what ``board_data_api._param`` emits: typed values arrive
    as ``stringValue`` plus a ``typeHint``. DECIMAL becomes a float so the
    fake's arithmetic matches the real ``numeric`` columns.
    """
    out: dict[str, Any] = {}
    for p in parameters or []:
        name = str(p.get("name") or "")
        val = p.get("value") or {}
        hint = str(p.get("typeHint") or "")
        if val.get("isNull"):
            out[name] = None
        elif "stringValue" in val:
            out[name] = float(val["stringValue"]) if hint == "DECIMAL" else val["stringValue"]
        elif "longValue" in val:
            out[name] = val["longValue"]
        elif "doubleValue" in val:
            out[name] = val["doubleValue"]
        elif "booleanValue" in val:
            out[name] = val["booleanValue"]
    return out


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def _unique_violation(constraint: str) -> board_data_api.DataApiError:
    return board_data_api.DataApiError(
        f'Data API: ERROR: duplicate key value violates unique constraint "{constraint}"; SQLState: 23505'
    )


class FakeAurora:
    """In-memory stand-in for the siutindei Data API tables and §5.7 views."""

    def __init__(self) -> None:
        self.plans: list[dict[str, Any]] = []
        self.subs: list[dict[str, Any]] = []
        self.invoices: list[dict[str, Any]] = []
        self.payments: list[dict[str, Any]] = []
        self.catalog: list[dict[str, Any]] = []
        self.provider_counts: dict[str, Any] | None = None
        self.funnel: list[dict[str, Any]] = []
        self.pipeline: list[dict[str, Any]] = []
        self.sqls: list[str] = []
        self.parameters: list[list[dict[str, Any]] | None] = []
        # When > 0, the next invoice INSERT loses a race: a competing row with
        # the same number lands first and the statement fails with 23505.
        self.race_invoice_inserts = 0

    def _sub_rows(self, sub: dict[str, Any]) -> dict[str, Any]:
        plan = next((pl for pl in self.plans if pl["id"] == sub.get("plan_id")), None)
        return {
            **sub,
            "plan_name": (plan or {}).get("name"),
            "price_hkd": (plan or {}).get("price_hkd"),
            "billing_period": (plan or {}).get("billing_period"),
        }

    def __call__(self, sql: str, parameters: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        self.sqls.append(sql)
        self.parameters.append(parameters)
        p = _unwrap(parameters)
        s = _norm(sql)
        low = s.lower()

        if low.startswith("insert into listing_plans"):
            self.plans.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "price_hkd": p["price"],
                    "billing_period": p["period"],
                    "active": True,
                }
            )
            return []
        if low.startswith("insert into invoices"):
            if self.race_invoice_inserts > 0:
                self.race_invoice_inserts -= 1
                self.invoices.append(
                    {
                        "id": f"racer-{len(self.invoices)}",
                        "subscription_id": p["sub"],
                        "number": p["number"],
                        "issued_on": p["issued"],
                        "due_on": p["due"],
                        "amount_hkd": p["amount"],
                        "status": "draft",
                        "fps_reference": f"RACE{len(self.invoices)}",
                        "pdf_key": None,
                    }
                )
                raise _unique_violation("invoices_number_key")
            if any(i["number"] == p["number"] for i in self.invoices):
                raise _unique_violation("invoices_number_key")
            if any(i["fps_reference"] == p["fps"] for i in self.invoices):
                raise _unique_violation("invoices_fps_reference_key")
            self.invoices.append(
                {
                    "id": p["id"],
                    "subscription_id": p["sub"],
                    "number": p["number"],
                    "issued_on": p["issued"],
                    "due_on": p["due"],
                    "amount_hkd": p["amount"],
                    "status": "draft",
                    "fps_reference": p["fps"],
                    "pdf_key": None,
                }
            )
            return []
        if low.startswith("insert into payments"):
            self.payments.append(
                {
                    "id": p["id"],
                    "invoice_id": p.get("inv"),
                    "received_on": p["received"],
                    "amount_hkd": p["amount"],
                    "payer_name": p.get("payer") or "",
                    "bank_reference": p.get("ref") or "",
                    "source": "manual",
                    "matched_by": p.get("who"),
                }
            )
            return []
        if low.startswith("update invoices set pdf_key"):
            inv = next((i for i in self.invoices if i["id"] == p["id"]), None)
            if inv:
                inv["pdf_key"] = p.get("key")
            return []
        if low.startswith("update invoices set status"):
            inv = next((i for i in self.invoices if i["id"] == p["id"]), None)
            if not inv:
                return []
            # Honour the statement's own WHERE status guard, as Postgres would.
            m = re.search(r"where id = :id and status (?:= '(\w+)'|in \(([^)]*)\))", low)
            if m:
                allowed = {m.group(1)} if m.group(1) else {x.strip().strip("'") for x in m.group(2).split(",")}
                if inv["status"] not in allowed:
                    return []
            target = re.search(r"set status = '(\w+)'", low)
            if target:
                inv["status"] = target.group(1)
            return []
        if low.startswith("update payments set invoice_id"):
            pay = next((x for x in self.payments if x["id"] == p["id"]), None)
            if pay:
                pay["invoice_id"] = p["inv"]
                pay["matched_by"] = p.get("who")
            return []

        if "from listing_subscriptions s" in low and "from invoices i" not in low:
            rows = [self._sub_rows(sub) for sub in self.subs if not p.get("status") or sub["status"] == p["status"]]
            return rows[: int(p.get("lim") or 100)]
        if "from listing_subscriptions where id" in low:
            return [dict(x) for x in self.subs if x["id"] == p.get("id")]
        if "count(*)" in low and "listing_subscriptions" in low:
            rows = [x for x in self.subs if x["status"] in ("trial", "active")]
            if "starts_on >= :since" in low:
                rows = [x for x in rows if str(x.get("starts_on") or "") >= str(p["since"])]
            return [{"n": len(rows)}]

        if "from invoices where number like" in low:
            prefix = str(p.get("p") or "").rstrip("%")
            matches = [i for i in self.invoices if str(i.get("number") or "").startswith(prefix)]
            matches.sort(key=lambda i: str(i.get("number") or ""), reverse=True)
            return [{"number": matches[0]["number"]}] if matches else []
        if "from invoices where id" in low or "from invoices where id = :id" in low:
            return [dict(x) for x in self.invoices if x["id"] == p.get("id")]
        if "sum(amount_hkd)" in low and "invoices" in low:
            paid = [i for i in self.invoices if i["status"] == "paid"]
            if "issued_on >= :since" in low:
                paid = [i for i in paid if str(i.get("issued_on") or "") >= str(p["since"])]
            return [{"total": sum(float(i["amount_hkd"]) for i in paid)}]
        if "from invoices i left join listing_subscriptions s" in low:
            rows = []
            for inv in self.invoices:
                if inv["status"] not in ("sent", "overdue"):
                    continue
                sub = next((x for x in self.subs if x["id"] == inv.get("subscription_id")), None) or {}
                rows.append(
                    {
                        **{k: inv.get(k) for k in ("id", "number", "amount_hkd", "status", "due_on", "fps_reference", "subscription_id")},
                        "organization_id": sub.get("organization_id"),
                        "payer_contact": sub.get("payer_contact"),
                    }
                )
            rows.sort(key=lambda r: str(r.get("due_on") or ""))
            return rows
        if "abs(amount_hkd - :amount)" in low:
            rows = []
            for inv in self.invoices:
                if inv["status"] not in ("draft", "sent", "overdue"):
                    continue
                amount_ok = abs(float(inv["amount_hkd"]) - float(p["amount"])) <= float(p["tol"])
                ref_ok = str(inv.get("fps_reference") or "").upper() == str(p["ref"])
                if amount_ok or ref_ok:
                    rows.append(dict(inv))
            rows.sort(key=lambda r: str(r.get("due_on") or ""))
            return rows[: int(p.get("lim") or 100)]
        if "from invoices" in low:
            rows = [dict(i) for i in self.invoices]
            m = re.search(r"where status in \(([^)]*)\)", low)
            if m:
                allowed = {x.strip().strip("'") for x in m.group(1).split(",")}
                rows = [i for i in rows if i["status"] in allowed]
            if p.get("status"):
                rows = [i for i in rows if i["status"] == p["status"]]
            return rows[: int(p.get("lim") or 100)]

        if "from payments where id" in low:
            return [dict(x) for x in self.payments if x["id"] == p.get("id")]
        if "from payments" in low:
            rows = [dict(x) for x in self.payments]
            if "invoice_id is not null" in low:
                rows = [x for x in rows if x.get("invoice_id")]
            return rows

        if "from v_catalog_provider_counts" in low:
            if self.provider_counts:
                return [dict(self.provider_counts)]
            return [{"providers": 0, "providers_with_venue": 0}]
        if "from v_catalog_health" in low:
            rows = list(self.catalog)
            if p.get("district"):
                rows = [r for r in rows if r.get("district") == p["district"]]
            if p.get("category"):
                rows = [r for r in rows if r.get("category") == p["category"]]
            return rows
        if "from v_funnel_daily" in low:
            rows = list(self.funnel)
            if p.get("dfrom"):
                rows = [r for r in rows if str(r.get("day")) >= str(p["dfrom"])]
            if p.get("dto"):
                rows = [r for r in rows if str(r.get("day")) <= str(p["dto"])]
            if p.get("district"):
                rows = [r for r in rows if r.get("district") == p["district"]]
            return rows
        if "from v_provider_pipeline" in low:
            rows = list(self.pipeline)
            if p.get("status"):
                rows = [r for r in rows if r.get("subscription_status") == p["status"]]
            return rows

        raise AssertionError(f"unhandled SQL: {sql}")


class ReceivablesTestCase(ToolsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = FakeAurora()
        board_data_api.set_executor_for_tests(self.db)
        self.addCleanup(lambda: board_data_api.set_executor_for_tests(None))
        self.db.plans.append(
            {
                "id": "plan-1",
                "name": "Store listing — monthly",
                "price_hkd": 388.0,
                "billing_period": "monthly",
                "active": True,
            }
        )
        self.db.subs.append(
            {
                "id": "sub-1",
                "organization_id": "org-1",
                "store_id": "store-1",
                "plan_id": "plan-1",
                "starts_on": "2026-08-01",
                "renews_on": "2026-10-01",
                "status": "active",
                "payer_contact": "billing@provider.example",
            }
        )
        self.db.catalog.append(
            {
                "district": "Tuen Mun",
                "category": "swimming",
                "activities": 12,
                "providers": 4,
                "stores": 3,
                "completeness": 0.75,
            }
        )
        self.db.funnel.append(
            {
                "day": "2026-09-01",
                "district": "Tuen Mun",
                "searches": 40,
                "listing_views": 20,
                "cta_taps": 5,
                "leads_relayed": 2,
                "bookings_confirmed": 1,
            }
        )
        self.db.pipeline.append(
            {
                "organization_id": "org-1",
                "organization_name": "Splash Ltd",
                "signed_up_on": "2026-07-01",
                "onboarding_step": "photos",
                "days_since_last_edit": 3,
                "subscription_status": "active",
            }
        )

    def _ctx(self, persona: str = "cfo", *, actor: str = "persona", **kwargs: Any) -> ToolContext:
        settings = board_store.load_settings(self.table)
        settings["tools"]["globalMode"] = kwargs.pop("global_mode", settings["tools"]["globalMode"])
        return ToolContext(
            table=self.table,
            settings=settings,
            persona_id=persona,
            display_name=persona.upper(),
            actor=actor,
            owner_sub="owner-1" if actor == "owner" else "",
        )


class TestFinanceReadsAndDraft(ReceivablesTestCase):
    def test_list_subscriptions_and_draft_invoice_number(self) -> None:
        listed = board_receivables.op_list_subscriptions(None, {})
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["subscriptions"][0]["plan_name"], "Store listing — monthly")
        year = date.today().year
        first = board_receivables.op_draft_invoice(
            None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "First invoice."}
        )
        self.assertTrue(first["ok"])
        self.assertEqual(first["number"], f"STD-{year}-0001")
        self.assertTrue(re.fullmatch(r"STD[0-9A-F]{8}", first["fpsReference"]))
        second = board_receivables.op_draft_invoice(
            None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "Second."}
        )
        self.assertEqual(second["number"], f"STD-{year}-0002")
        self.assertEqual(len(self.db.invoices), 2)

    def test_aging_buckets(self) -> None:
        today = date.today()
        self.db.invoices.extend(
            [
                {
                    "id": "inv-cur",
                    "subscription_id": "sub-1",
                    "number": "STD-2026-0001",
                    "issued_on": today.isoformat(),
                    "due_on": today.isoformat(),
                    "amount_hkd": 100,
                    "status": "sent",
                    "fps_reference": "STDAAAA0001",
                    "pdf_key": None,
                },
                {
                    "id": "inv-d7",
                    "subscription_id": "sub-1",
                    "number": "STD-2026-0002",
                    "issued_on": (today - timedelta(days=10)).isoformat(),
                    "due_on": (today - timedelta(days=10)).isoformat(),
                    "amount_hkd": 200,
                    "status": "sent",
                    "fps_reference": "STDAAAA0002",
                    "pdf_key": None,
                },
                {
                    "id": "inv-d35",
                    "subscription_id": "sub-1",
                    "number": "STD-2026-0003",
                    "issued_on": (today - timedelta(days=40)).isoformat(),
                    "due_on": (today - timedelta(days=40)).isoformat(),
                    "amount_hkd": 300,
                    "status": "overdue",
                    "fps_reference": "STDAAAA0003",
                    "pdf_key": None,
                },
            ]
        )
        aging = board_receivables.op_aging_report(None, {})
        self.assertEqual(len(aging["buckets"]["current"]), 1)
        self.assertEqual(len(aging["buckets"]["d7"]), 1)
        self.assertEqual(len(aging["buckets"]["d35"]), 1)
        self.assertEqual(aging["outstandingHkd"], 600.0)
        status, body = self.call("/siu-tin-dei/board/receivables")
        self.assertEqual(status, 200)
        self.assertTrue(body["configured"])
        self.assertEqual(body["aging"]["outstandingHkd"], 600.0)
        digest = board_receivables.digest_for_context()
        self.assertEqual(digest["overdue"], 2)
        status, overview = self.call("/siu-tin-dei/board")
        self.assertEqual(status, 200)
        self.assertEqual(overview["overdueInvoiceCount"], 2)

    def test_unit_economics(self) -> None:
        self.db.invoices.append(
            {
                "id": "inv-paid",
                "subscription_id": "sub-1",
                "number": "STD-2026-0099",
                "issued_on": "2026-08-01",
                "due_on": "2026-08-15",
                "amount_hkd": 388,
                "status": "paid",
                "fps_reference": "STPAID001",
                "pdf_key": None,
            }
        )
        board_store.record_ads_spend(self.table, daily_usd=4.0, monthly_usd=4.0)
        out = board_receivables.op_unit_economics(self._ctx(), {})
        self.assertEqual(out["paidInvoicesHkd"], 388.0)
        self.assertEqual(out["activeSubscriptions"], 1)
        self.assertEqual(out["metaAdsRecordedMonthlyUsd"], 4.0)
        self.assertIn("Meta ads", out["note"])


class TestFinanceWritesAndGuards(ReceivablesTestCase):
    def test_match_payment_guard_and_act(self) -> None:
        self.db.invoices.append(
            {
                "id": "inv-1",
                "subscription_id": "sub-1",
                "number": "STD-2026-0001",
                "issued_on": "2026-09-01",
                "due_on": "2026-09-15",
                "amount_hkd": 388,
                "status": "sent",
                "fps_reference": "STDFPS0001",
                "pdf_key": None,
            }
        )
        self.db.payments.append(
            {
                "id": "pay-mismatch",
                "invoice_id": None,
                "received_on": "2026-09-02",
                "amount_hkd": 100,
                "payer_name": "Splash",
                "bank_reference": "OTHER",
                "source": "manual",
                "matched_by": None,
            }
        )
        self.db.payments.append(
            {
                "id": "pay-ok",
                "invoice_id": None,
                "received_on": "2026-09-02",
                "amount_hkd": 388,
                "payer_name": "Splash",
                "bank_reference": "STDFPS0001",
                "source": "manual",
                "matched_by": None,
            }
        )
        ctx = self._ctx(global_mode="act")
        blocked = execute_call(
            ctx,
            REGISTRY["finance_match_payment"],
            {"paymentId": "pay-mismatch", "invoiceId": "inv-1", "reason": "Try a match."},
        )
        self.assertEqual(blocked.status, "pending_approval")
        self.assertIn("does not agree", blocked.result["message"])
        ok = execute_call(
            ctx,
            REGISTRY["finance_match_payment"],
            {"paymentId": "pay-ok", "invoiceId": "inv-1", "reason": "FPS and amount agree."},
        )
        self.assertEqual(ok.status, "ok")
        self.assertEqual(self.db.invoices[0]["status"], "paid")
        self.assertEqual(self.db.payments[1]["invoice_id"], "inv-1")

    def test_send_invoice_guard_without_allow_list(self) -> None:
        draft = board_receivables.op_draft_invoice(
            None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "Draft."}
        )
        ctx = self._ctx(global_mode="act")
        out = execute_call(
            ctx,
            REGISTRY["finance_send_invoice"],
            {"invoiceId": draft["invoiceId"], "reason": "Send it."},
        )
        self.assertEqual(out.status, "pending_approval")
        self.assertIn("allow-list", out.result["message"])
        preview = board_receivables.owner_preview_send(
            ctx, {"invoiceId": draft["invoiceId"], "reason": "Send it."}, op="finance_send_invoice"
        )
        self.assertEqual(preview["kind"], "email")
        self.assertEqual(preview["from"], "billing@siutindei.com")
        self.assertEqual(preview["to"], ["billing@provider.example"])

    def test_record_manual_payment_and_price_change(self) -> None:
        owner = self._ctx(actor="owner")
        pay = execute_call(
            owner,
            REGISTRY["finance_record_manual_payment"],
            {"amountHkd": 50, "payerName": "Cash customer", "reason": "Cheque at the counter."},
        )
        self.assertEqual(pay.status, "ok")
        self.assertEqual(self.db.payments[0]["source"], "manual")
        plan = execute_call(
            owner,
            REGISTRY["finance_propose_price_change"],
            {
                "name": "Store listing — annual",
                "priceHkd": 3880,
                "billingPeriod": "annual",
                "reason": "Seed the first annual plan.",
            },
        )
        self.assertEqual(plan.status, "ok")
        self.assertEqual(self.db.plans[-1]["name"], "Store listing — annual")


class TestMirrorAndDunning(ReceivablesTestCase):
    def test_mirror_is_idempotent(self) -> None:
        today = date.today()
        self.db.invoices.append(
            {
                "id": "inv-open",
                "subscription_id": "sub-1",
                "number": "STD-2026-0001",
                "issued_on": today.isoformat(),
                "due_on": today.isoformat(),
                "amount_hkd": 388,
                "status": "sent",
                "fps_reference": "STDFPS0001",
                "pdf_key": None,
            }
        )
        self.db.payments.append(
            {
                "id": "pay-1",
                "invoice_id": "inv-other",
                "received_on": today.isoformat(),
                "amount_hkd": 100,
                "payer_name": "A",
                "bank_reference": "X",
                "source": "manual",
                "matched_by": "manual",
            }
        )
        first = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual(first["linesWritten"], 2)
        second = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual(second["linesWritten"], 0)
        from finance_store import _load_finance_owner

        book = _load_finance_owner(self.table, "siuTinDei")
        ids = {ln["id"] for ln in book["lines"]}
        self.assertIn("recv-inv-inv-open", ids)
        self.assertIn("recv-pay-pay-1", ids)
        self.assertTrue(all("[receivables]" in ln["description"] for ln in book["lines"]))

    def test_dunning_creates_one_approval_per_invoice(self) -> None:
        due = (date.today() - timedelta(days=7)).isoformat()
        self.db.invoices.append(
            {
                "id": "inv-d7",
                "subscription_id": "sub-1",
                "number": "STD-2026-0008",
                "issued_on": due,
                "due_on": due,
                "amount_hkd": 388,
                "status": "sent",
                "fps_reference": "STDFPS0008",
                "pdf_key": None,
            }
        )
        with patch.object(board_store, "records_table", return_value=self.table):
            first = board_receivables.handle_dunning_trigger({})
            again = board_receivables.handle_dunning_trigger({})
        self.assertEqual(first["created"], 1)
        self.assertEqual(again["created"], 0)
        pending = [a for a in board_store.list_approvals(self.table) if a.get("status") == "pending"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["op"], "finance_send_reminder")
        self.assertEqual(pending[0]["arguments"]["invoiceId"], "inv-d7")

    def test_schedule_triggers_dispatch(self) -> None:
        with patch.object(board_store, "records_table", return_value=self.table):
            dispatch.lambda_handler({"internal": "board_receivables_mirror"}, None)
            dispatch.lambda_handler({"internal": "board_dunning"}, None)


class TestProductViews(ReceivablesTestCase):
    def test_views_are_selects_only(self) -> None:
        catalog = board_product.op_catalog_health(None, {"district": "Tuen Mun"})
        self.assertEqual(catalog["rows"][0]["activities"], 12)
        funnel = board_product.op_funnel(None, {"from": "2026-09-01", "to": "2026-09-30"})
        self.assertEqual(funnel["rows"][0]["leads_relayed"], 2)
        pipeline = board_product.op_provider_pipeline(None, {"status": "active"})
        self.assertEqual(pipeline["count"], 1)
        for sql in self.db.sqls:
            self.assertTrue(sql.lstrip().upper().startswith("SELECT"), sql)
            self.assertIn("v_", sql.lower())

    def test_flag_listing_writes_action_not_catalog(self) -> None:
        ctx = self._ctx("cpo", actor="owner")
        out = execute_call(
            ctx,
            REGISTRY["product_flag_listing"],
            {"listingId": "act-99", "reason": "Photos look stock."},
        )
        self.assertEqual(out.status, "ok")
        actions = board_store.list_actions(self.table)
        self.assertTrue(any(a.get("title") == "Review listing act-99" for a in actions))
        self.assertFalse(any("update" in s.lower() or "insert" in s.lower() for s in self.db.sqls))

    def test_context_pack_mentions_receivables(self) -> None:
        due = (date.today() - timedelta(days=10)).isoformat()
        self.db.invoices.append(
            {
                "id": "inv-d7",
                "subscription_id": "sub-1",
                "number": "STD-2026-0008",
                "issued_on": due,
                "due_on": due,
                "amount_hkd": 388,
                "status": "sent",
                "fps_reference": "STDFPS0008",
                "pdf_key": None,
            }
        )
        settings = board_store.load_settings(self.table)
        pack = board_context.build_context_pack(self.table, settings, roster=[])
        self.assertIn("Receivables", pack["text"])
        self.assertIn("past due", pack["text"])


class TestDataApiNotConfigured(BoardTestCase):
    def test_aging_for_owner_empty_without_cluster(self) -> None:
        board_data_api.set_executor_for_tests(None)
        self.assertFalse(board_receivables.configured())
        body = board_receivables.aging_for_owner()
        self.assertFalse(body["configured"])
        self.assertEqual(body["invoices"], [])


if __name__ == "__main__":
    unittest.main()
