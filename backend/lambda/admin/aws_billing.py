"""AWS invoice split from Cost Explorer tags.

LX Software pays one AWS invoice for this account. Cost Explorer UnblendedCost
grouped by the active cost-allocation tags ``Organization`` and ``Project`` is
the source of the company split (Siu Tin Dei, Evolve Sprouts, LX Software).
AWS's own invoice PDF is still one account total; ``GET /aws/usage.pdf`` is
the internal allocation PDF.

Tag map (first matching company in ``contracts/aws-billing.json`` wins):

- Organization=LX Software and Project=Siu Tin Dei → Siu Tin Dei
- Organization=Evolve Sprouts → Evolve Sprouts
- Organization=LX Software (any other Project) → LX Software
- anything else (Personal, untagged) → Unallocated
"""

from __future__ import annotations

import base64
from calendar import month_name
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs

from botocore.exceptions import ClientError

import board_invoice_pdf
from contract_constants import (
    AWS_BILLING_COMPANIES,
    AWS_BILLING_COST_ALLOCATION_TAGS,
    AWS_BILLING_CURRENCY,
    AWS_BILLING_PAYER,
)
from http_common import _json_response

ORG_TAG = "Organization"
PROJECT_TAG = "Project"
UNALLOCATED_ID = "unallocated"
UNALLOCATED_LABEL = "Unallocated"
OWNER_LABELS: dict[str, str] = {
    "siuTinDei": "Siu Tin Dei",
    "lxSoftware": "LX Software",
    "evolveSprouts": "Evolve Sprouts",
}
_MAX_RANGE_DAYS = 93
_DATE_FMT = "%Y-%m-%d"


class AwsBillingError(RuntimeError):
    """User-facing failure talking to Cost Explorer."""


def _ce() -> Any:
    import boto3

    return boto3.client("ce", region_name="us-east-1")  # noqa: S311 - AWS SDK


def payer_payload() -> dict[str, str]:
    payer_id = str(AWS_BILLING_PAYER or "lxSoftware")
    return {"id": payer_id, "label": OWNER_LABELS.get(payer_id, payer_id)}


def company_label(company_id: str) -> str:
    for row in AWS_BILLING_COMPANIES:
        if isinstance(row, dict) and str(row.get("id") or "") == company_id:
            return str(row.get("label") or company_id)
    if company_id == UNALLOCATED_ID:
        return UNALLOCATED_LABEL
    return OWNER_LABELS.get(company_id, company_id)


def parse_ce_tag(raw: str, key: str) -> str:
    """Cost Explorer group keys look like ``Organization$Evolve Sprouts``."""
    text = str(raw or "")
    prefix = f"{key}$"
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


def assign_company(organization: str, project: str) -> str:
    """First matching catalog row wins; otherwise unallocated."""
    org = (organization or "").strip()
    proj = (project or "").strip()
    for row in AWS_BILLING_COMPANIES:
        if not isinstance(row, dict):
            continue
        want_org = str(row.get("organization") or "").strip()
        want_proj = str(row.get("project") or "").strip()
        if want_org and org != want_org:
            continue
        if want_proj and proj != want_proj:
            continue
        company_id = str(row.get("id") or "").strip()
        if company_id:
            return company_id
    return UNALLOCATED_ID


def default_invoice_range(today: date | None = None) -> tuple[str, str]:
    """Last complete UTC calendar month (the period an AWS invoice covers)."""
    day = today or datetime.now(timezone.utc).date()
    first_this = day.replace(day=1)
    start = (first_this - timedelta(days=1)).replace(day=1)
    last = first_this - timedelta(days=1)
    return start.strftime(_DATE_FMT), last.strftime(_DATE_FMT)


def _parse_day(raw: str, field: str) -> date:
    try:
        return datetime.strptime(raw, _DATE_FMT).date()
    except ValueError as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD") from exc


def resolve_range(from_day: str, to_day: str) -> tuple[date, date, date]:
    """Return inclusive start, inclusive end, exclusive Cost Explorer end."""
    start = _parse_day(from_day, "from")
    end_inclusive = _parse_day(to_day, "to")
    if end_inclusive < start:
        raise ValueError("to must be on or after from")
    if (end_inclusive - start).days + 1 > _MAX_RANGE_DAYS:
        raise ValueError(f"range must be {_MAX_RANGE_DAYS} days or fewer")
    return start, end_inclusive, end_inclusive + timedelta(days=1)


def _amount(group: dict[str, Any]) -> float:
    metrics = group.get("Metrics") if isinstance(group, dict) else None
    blob = (metrics or {}).get("UnblendedCost") if isinstance(metrics, dict) else None
    raw = (blob or {}).get("Amount") if isinstance(blob, dict) else 0
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def _collect_groups(ce: Any, start: str, end: str) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [
                {"Type": "TAG", "Key": ORG_TAG},
                {"Type": "TAG", "Key": PROJECT_TAG},
            ],
        }
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_cost_and_usage(**kwargs)
        for period in resp.get("ResultsByTime") or []:
            for group in period.get("Groups") or []:
                if isinstance(group, dict):
                    groups.append(group)
        token = resp.get("NextPageToken")
        if not token:
            break
    return groups


def _empty_company(company_id: str, label: str) -> dict[str, Any]:
    return {
        "id": company_id,
        "label": label,
        "usd": 0.0,
        "share": 0.0,
        "projects": {},
    }


def _catalog_companies() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in AWS_BILLING_COMPANIES:
        if not isinstance(row, dict):
            continue
        company_id = str(row.get("id") or "").strip()
        if not company_id or company_id in seen:
            continue
        seen.add(company_id)
        out.append(_empty_company(company_id, str(row.get("label") or company_id)))
    return out


def split_groups(groups: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = {row["id"]: row for row in _catalog_companies()}
    for group in groups:
        keys = group.get("Keys") or ["", ""]
        organization = parse_ce_tag(keys[0] if len(keys) > 0 else "", ORG_TAG)
        project = parse_ce_tag(keys[1] if len(keys) > 1 else "", PROJECT_TAG)
        usd = _amount(group)
        if usd == 0:
            continue
        company_id = assign_company(organization, project)
        bucket = buckets.get(company_id)
        if bucket is None:
            bucket = _empty_company(company_id, company_label(company_id))
            buckets[company_id] = bucket
        bucket["usd"] = float(bucket["usd"]) + usd
        project_key = project or "(untagged)"
        projects = bucket["projects"]
        projects[project_key] = float(projects.get(project_key) or 0) + usd
    total = sum(float(row["usd"]) for row in buckets.values())
    ordered_ids = [row["id"] for row in _catalog_companies()]
    extra_ids = [cid for cid in buckets if cid not in ordered_ids]
    extra_ids.sort(key=lambda cid: (-float(buckets[cid]["usd"]), cid))
    companies: list[dict[str, Any]] = []
    for company_id in ordered_ids + extra_ids:
        bucket = buckets[company_id]
        usd = round(float(bucket["usd"]), 2)
        share = (usd / total) if total else 0.0
        project_rows = [
            {"id": name, "label": name, "usd": round(amount, 2)}
            for name, amount in sorted(
                bucket["projects"].items(), key=lambda item: (-item[1], item[0])
            )
        ]
        companies.append(
            {
                "id": company_id,
                "label": bucket["label"],
                "usd": usd,
                "share": round(share, 4),
                "projects": project_rows,
            }
        )
    return {
        "totalUsd": round(total, 2),
        "companies": companies,
    }


def fetch_usage(
    *,
    from_day: str,
    to_day: str,
    ce: Any | None = None,
) -> dict[str, Any]:
    start, end_inclusive, ce_end = resolve_range(from_day, to_day)
    try:
        groups = _collect_groups(
            ce or _ce(), start.strftime(_DATE_FMT), ce_end.strftime(_DATE_FMT)
        )
    except ClientError as exc:
        message = exc.response.get("Error", {}).get("Message", str(exc))
        raise AwsBillingError(f"Cost Explorer: {message}") from exc
    split = split_groups(groups)
    return {
        "from": start.strftime(_DATE_FMT),
        "to": end_inclusive.strftime(_DATE_FMT),
        "currency": AWS_BILLING_CURRENCY,
        "payer": payer_payload(),
        "source": "cost-explorer",
        "costAllocationTags": list(AWS_BILLING_COST_ALLOCATION_TAGS),
        "total": {"usd": split["totalUsd"]},
        "companies": split["companies"],
    }


def period_label(from_day: str, to_day: str) -> str:
    start = _parse_day(from_day, "from")
    end = _parse_day(to_day, "to")
    if start.year == end.year and start.month == end.month and start.day == 1:
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        if end == next_month - timedelta(days=1):
            return f"{month_name[start.month]} {start.year}"
    return f"{from_day} to {to_day}"


def render_allocation_pdf(payload: dict[str, Any]) -> bytes:
    from_day = str(payload.get("from") or "")
    to_day = str(payload.get("to") or "")
    payer = payload.get("payer") if isinstance(payload.get("payer"), dict) else {}
    total = payload.get("total") if isinstance(payload.get("total"), dict) else {}
    total_usd = float(total.get("usd") or 0)
    lines = [
        "LX Software — AWS cost allocation",
        f"Period {period_label(from_day, to_day)} ({from_day} to {to_day})",
        f"Payer: {payer.get('label') or 'LX Software'}",
        "Source: Cost Explorer UnblendedCost by Organization + Project tags",
        "AWS's own invoice PDF is one account total; this PDF is the internal split.",
        "",
        f"Total  USD {total_usd:.2f}",
        "",
    ]
    companies = payload.get("companies") if isinstance(payload.get("companies"), list) else []
    for company in companies:
        if not isinstance(company, dict):
            continue
        usd = float(company.get("usd") or 0)
        share = float(company.get("share") or 0) * 100
        lines.append(
            f"{company.get('label') or company.get('id')}  USD {usd:.2f}  ({share:.1f}%)"
        )
        projects = company.get("projects") if isinstance(company.get("projects"), list) else []
        for project in projects:
            if not isinstance(project, dict):
                continue
            lines.append(
                f"  {project.get('label') or project.get('id')}  USD {float(project.get('usd') or 0):.2f}"
            )
        lines.append("")
    return board_invoice_pdf.render_text_pdf(lines)


def pdf_filename(from_day: str) -> str:
    return f"lx-software-aws-{from_day[:7]}.pdf"


def _pdf_response(data: bytes, filename: str) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/pdf",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
        "isBase64Encoded": True,
        "body": base64.b64encode(data).decode("ascii"),
    }


def _query_range(event: dict[str, Any]) -> tuple[str, str]:
    qs = parse_qs(event.get("rawQueryString") or "")
    default_from, default_to = default_invoice_range()
    from_day = (qs.get("from", [default_from])[0] or default_from).strip()
    to_day = (qs.get("to", [default_to])[0] or default_to).strip()
    return from_day, to_day


def handle_usage_get(event: dict[str, Any]) -> dict[str, Any]:
    """GET /aws/usage?from=YYYY-MM-DD&to=YYYY-MM-DD (last complete month default)."""
    from_day, to_day = _query_range(event)
    try:
        payload = fetch_usage(from_day=from_day, to_day=to_day)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    except AwsBillingError as exc:
        return _json_response(502, {"message": str(exc)})
    return _json_response(200, payload)


def handle_usage_pdf(event: dict[str, Any]) -> dict[str, Any]:
    """GET /aws/usage.pdf?from=YYYY-MM-DD&to=YYYY-MM-DD."""
    from_day, to_day = _query_range(event)
    try:
        payload = fetch_usage(from_day=from_day, to_day=to_day)
    except ValueError as exc:
        return _json_response(400, {"message": str(exc)})
    except AwsBillingError as extra:
        return _json_response(502, {"message": str(extra)})
    return _pdf_response(render_allocation_pdf(payload), pdf_filename(payload["from"]))
