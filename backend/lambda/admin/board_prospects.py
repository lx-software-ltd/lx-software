"""Prospect upsert, scoring, qualification, contact finding and merge."""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any
from urllib.parse import urlparse

import board_crawl
import board_hk
import board_opendata
import board_pii
import board_store
from contract_constants import BOARD_STAFF_PROSPECT_STAGES, BOARD_STAFF_PROSPECT_TYPES
from http_common import _log_event

BUSINESS_LOCAL_PARTS = frozenset(
    {
        "info",
        "hello",
        "enquiry",
        "enquiries",
        "contact",
        "booking",
        "bookings",
        "admin",
        "office",
        "partnerships",
        "marketing",
        "hi",
        "team",
    }
)
NEEDS_CONTACT_DAILY_CAP = 20
OWNER_STAGES = frozenset({"suppressed", "declined", "qualified", "parked"})
MULTI_LABEL_TLDS = frozenset({"com.hk", "org.hk", "net.hk", "edu.hk", "gov.hk", "idv.hk", "co.uk"})
PUBLIC_MAILBOX_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "me.com",
        "qq.com",
        "163.com",
        "126.com",
        "ymail.com",
        "protonmail.com",
    }
)
EMAIL_RE = board_pii.EMAIL_RE
MAILTO_RE = re.compile(r"mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", re.I)


class ProspectError(ValueError):
    """Prospect input or state is invalid."""


def registrable_domain(website: str) -> str:
    raw = str(website or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return host
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_LABEL_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def e164_phone(phone: str) -> str:
    digits = re.sub(r"[^\d+]", "", str(phone or ""))
    if not digits:
        return ""
    if digits.startswith("+"):
        return "+" + re.sub(r"\D", "", digits)
    local = re.sub(r"\D", "", digits)
    if len(local) == 8:
        return f"+852{local}"
    if local.startswith("852") and len(local) == 11:
        return f"+{local}"
    return f"+{local}" if local else ""


def dedupe_key(website: str = "", phone: str = "", place_id: str = "") -> str:
    domain = registrable_domain(website)
    if domain:
        return domain
    phone_key = e164_phone(phone)
    if phone_key:
        return phone_key
    pid = str(place_id or "").strip()
    if pid:
        return pid
    return ""


def _normalise_name(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def _district(value: str, address: str = "") -> str:
    text = str(value or "").strip()
    mapped = board_hk.district_from_address(text) or board_hk.district_from_address(address)
    if mapped:
        return mapped
    if text:
        # Already an 18-district English label.
        labels = {label for _, label in board_hk.HK_DISTRICTS}
        if text in labels:
            return text
    return "unknown"


def _valid_type(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw not in BOARD_STAFF_PROSPECT_TYPES:
        raise ProspectError(f"type must be one of {', '.join(BOARD_STAFF_PROSPECT_TYPES)}")
    return raw


def upsert(
    table: Any,
    *,
    name: str,
    type: str,
    district: str = "",
    source: str = "",
    website: str = "",
    phone: str = "",
    email: str = "",
    place_id: str = "",
    raw: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    display = " ".join(str(name or "").split())
    if not display:
        raise ProspectError("name is required")
    ptype = _valid_type(type)
    website = str(website or "").strip()
    phone = e164_phone(phone)
    email = board_pii.normalize_email(email)
    place_id = str(place_id or "").strip()
    district = _district(district, " ".join(str((raw or {}).get("address") or "")))
    key = dedupe_key(website, phone, place_id)
    existing_id = board_store.get_prospect_by_dedupe(table, key) if key else None
    if not existing_id and email:
        existing_id = board_store.get_prospect_by_dedupe(table, email)
    now = board_store.now_iso()
    settings = board_store.load_settings(table)
    if existing_id:
        row = board_store.get_prospect(table, existing_id) or {}
        created = False
        if source != "owner" and row.get("type"):
            ptype = str(row.get("type") or ptype)
    else:
        row = {
            "prospectId": board_store.new_id(),
            "stage": "discovered",
            "touches": [],
            "createdAt": now,
        }
        created = True
    merged_raw = {**(row.get("raw") or {}), **(raw or {})}
    row.update(
        {
            "name": display,
            "type": ptype,
            "district": district,
            "source": str(source or row.get("source") or "")[:40],
            "website": website or str(row.get("website") or ""),
            "phone": phone or str(row.get("phone") or ""),
            "email": email or str(row.get("email") or ""),
            "placeId": place_id or str(row.get("placeId") or ""),
            "raw": merged_raw,
            "updatedAt": now,
        }
    )
    if email:
        if _is_business_address(email, allow_personal=_personal_allowed(settings)):
            if not row.get("contact"):
                row["contact"] = email
        else:
            merged_raw["rejectedEmail"] = email
            row["raw"] = merged_raw
            row["contactRejected"] = "personal"
    board_store.put_prospect(table, row)
    _index_keys(table, row)
    return row, created


def upsert_prospect(table: Any, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Entry point used by ``board_intel.on_brief_delivered``."""
    return upsert(
        table,
        name=str(row.get("name") or ""),
        type=str(row.get("type") or "provider"),
        district=str(row.get("district") or ""),
        source=str(row.get("source") or "intel"),
        website=str(row.get("website") or row.get("url") or ""),
        phone=str(row.get("phone") or ""),
        email=str(row.get("email") or row.get("contact") or ""),
        place_id=str(row.get("placeId") or row.get("place_id") or ""),
        raw=row.get("raw") if isinstance(row.get("raw"), dict) else {k: v for k, v in row.items() if k not in {"name", "type"}},
    )


def _index_keys(table: Any, row: dict[str, Any]) -> None:
    pid = str(row.get("prospectId") or "")
    keys = [
        dedupe_key(str(row.get("website") or ""), str(row.get("phone") or ""), str(row.get("placeId") or "")),
        board_pii.normalize_email(str(row.get("email") or "")),
        board_pii.normalize_email(str(row.get("contact") or "")),
        registrable_domain(str(row.get("website") or "")),
    ]
    contact = str(row.get("contact") or row.get("email") or "")
    website_domain = registrable_domain(str(row.get("website") or ""))
    if "@" in contact:
        contact_domain = contact.rsplit("@", 1)[1].lower()
        if contact_domain == website_domain and not is_public_mailbox_domain(contact_domain):
            keys.append(contact_domain)
    for key in keys:
        if key and not is_public_mailbox_domain(str(key)):
            board_store.put_prospect_key(table, key, pid)


def is_public_mailbox_domain(domain: str) -> bool:
    return str(domain or "").strip().lower() in PUBLIC_MAILBOX_DOMAINS


def lookup_by_address(table: Any, address: str) -> dict[str, Any] | None:
    """Exact address first; domain fallback only for non-public mailboxes."""
    addr = board_pii.normalize_email(address)
    if not addr:
        return None
    pid = board_store.get_prospect_by_dedupe(table, addr)
    if not pid and "@" in addr:
        domain = addr.split("@", 1)[1]
        if not is_public_mailbox_domain(domain):
            pid = board_store.get_prospect_by_dedupe(table, domain)
    if not pid:
        return None
    return board_store.get_prospect(table, pid)


def types_enabled(settings: dict[str, Any]) -> list[str]:
    raw = ((settings.get("boundaries") or {}).get("outreach") or {}).get("typesEnabled") or []
    return [str(x) for x in raw if str(x) in BOARD_STAFF_PROSPECT_TYPES]


def score(table: Any, settings: dict[str, Any], prospect: dict[str, Any]) -> tuple[int, str]:
    import board_budget
    import board_pii as pii

    rubric = str(((settings.get("boundaries") or {}).get("outreach") or {}).get("fitRubric") or board_store.DEFAULT_FIT_RUBRIC)
    homepage = ""
    website = str(prospect.get("website") or "")
    if website:
        try:
            fetched = board_crawl.fetch(website)
            homepage = board_crawl.digest(board_crawl.normalise(board_crawl.html_to_text(fetched.text)))
        except Exception as exc:
            _log_event("warning", tag="board_prospect_homepage_failed", error=str(exc)[:200])
            homepage = ""
    pseud = pii.Pseudonymizer(table)
    public = {
        "name": prospect.get("name"),
        "type": prospect.get("type"),
        "district": prospect.get("district"),
        "website": website,
        "rating": (prospect.get("raw") or {}).get("rating"),
        "email": pseud.alias_for_address(str(prospect.get("email") or "")),
        "phone": pseud.alias_for("phone", str(prospect.get("phone") or "")) if prospect.get("phone") else "",
    }
    try:
        pseud.save()
    except Exception as exc:
        _log_event("warning", tag="board_prospect_mask_save_failed", error=str(exc)[:200])
    try:
        completion = board_budget.board_completion(
            table=table,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Score this organisation for Siu Tin Dei using the rubric. "
                        "Reply with JSON only: {\"score\":0,\"note\":\"\"}."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"rubric": rubric, "prospect": public, "homepage": homepage[:4000]}),
                },
            ],
            model=board_budget.model_for("standup", settings),
            timeout=20,
            json_mode=True,
            temperature=0,
            max_tokens=300,
            tag="board_prospect_score",
        )
        parsed = json.loads(completion.text or "{}")
        score_n = int(parsed.get("score") or 0)
        note = str(parsed.get("note") or "")[:800]
    except Exception as exc:
        _log_event("warning", tag="board_prospect_score_failed", error=str(exc)[:200])
        score_n = 50
        note = "desk score unavailable; defaulted to 50"
    score_n = max(0, min(100, score_n))
    prospect["score"] = score_n
    prospect["fitNote"] = note
    prospect["updatedAt"] = board_store.now_iso()
    board_store.put_prospect(table, prospect)
    return score_n, note


def qualify(table: Any, settings: dict[str, Any], prospect: dict[str, Any]) -> dict[str, Any]:
    enabled = set(types_enabled(settings))
    ptype = str(prospect.get("type") or "")
    try:
        score_n = int(prospect.get("score") if prospect.get("score") is not None else -1)
    except (TypeError, ValueError):
        score_n = -1
    if ptype not in enabled:
        prospect["stage"] = "parked"
    elif score_n >= 60:
        prospect["stage"] = "qualified"
        prospect["qualifiedAt"] = prospect.get("qualifiedAt") or board_store.now_iso()
    else:
        prospect["stage"] = "discovered"
    prospect["updatedAt"] = board_store.now_iso()
    board_store.put_prospect(table, prospect)
    _index_keys(table, prospect)
    return prospect


def _personal_allowed(settings: dict[str, Any]) -> bool:
    return bool(((settings.get("boundaries") or {}).get("outreach") or {}).get("personalAddressesAllowed"))


def _is_business_address(address: str, *, allow_personal: bool) -> bool:
    addr = board_pii.normalize_email(address)
    if "@" not in addr:
        return False
    local = addr.split("@", 1)[0]
    if allow_personal:
        return True
    return local in BUSINESS_LOCAL_PARTS


def _needs_contact_count(table: Any) -> int:
    hit = board_store.get_cache(table, f"needscontact:{board_hk.today_hkt()}")
    if hit and isinstance(hit.get("payload"), dict):
        try:
            return int(hit["payload"].get("count") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _bump_needs_contact(table: Any) -> None:
    n = _needs_contact_count(table) + 1
    board_store.put_cache(table, f"needscontact:{board_hk.today_hkt()}", {"count": n}, ttl_seconds=2 * 86400)


def find_contact(table: Any, settings: dict[str, Any], prospect: dict[str, Any]) -> str | None:
    allow_personal = _personal_allowed(settings)
    candidates: list[str] = []
    for raw in (prospect.get("email"), prospect.get("contact"), (prospect.get("raw") or {}).get("email")):
        if raw:
            candidates.append(board_pii.normalize_email(str(raw)))
    website = str(prospect.get("website") or "")
    if website and _needs_contact_count(table) < NEEDS_CONTACT_DAILY_CAP:
        pages = [website]
        parsed = urlparse(website if "://" in website else f"https://{website}")
        origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
        if board_crawl.host_is_blocked(parsed.hostname or parsed.netloc):
            pages = []
        else:
            pages.extend([f"{origin}/contact", f"{origin}/contact-us", f"{origin}/enquiry"])
        for url in pages:
            try:
                fetched = board_crawl.fetch(url)
            except Exception:
                continue
            text = fetched.text or ""
            for match in list(MAILTO_RE.findall(text)) + EMAIL_RE.findall(text):
                candidates.append(board_pii.normalize_email(match))
    chosen = next((c for c in candidates if _is_business_address(c, allow_personal=allow_personal)), "")
    if chosen:
        prospect["contact"] = chosen
        prospect["email"] = prospect.get("email") or chosen
        prospect["updatedAt"] = board_store.now_iso()
        board_store.put_prospect(table, prospect)
        _index_keys(table, prospect)
        return chosen
    prospect["contact"] = None
    prospect["updatedAt"] = board_store.now_iso()
    board_store.put_prospect(table, prospect)
    _bump_needs_contact(table)
    return None


def possible_duplicates(table: Any, prospect: dict[str, Any]) -> list[dict[str, Any]]:
    name = _normalise_name(str(prospect.get("name") or ""))
    district = str(prospect.get("district") or "")
    pid = str(prospect.get("prospectId") or "")
    out: list[dict[str, Any]] = []
    if not name:
        return out
    for row in board_store.list_prospects(table, limit=400):
        other_id = str(row.get("prospectId") or "")
        if other_id == pid:
            continue
        if _normalise_name(str(row.get("name") or "")) == name and str(row.get("district") or "") == district:
            out.append({"prospectId": other_id, "name": row.get("name"), "stage": row.get("stage")})
        if len(out) >= 8:
            break
    return out


def merge(table: Any, source_id: str, into_id: str) -> dict[str, Any]:
    if source_id == into_id:
        raise ProspectError("cannot merge a prospect into itself")
    source = board_store.get_prospect(table, source_id)
    dest = board_store.get_prospect(table, into_id)
    if not source or not dest:
        raise KeyError("prospect not found")
    for field in ("website", "phone", "email", "contact", "placeId", "fitNote"):
        if not dest.get(field) and source.get(field):
            dest[field] = source[field]
    if dest.get("score") is None and source.get("score") is not None:
        dest["score"] = source["score"]
    dest["raw"] = {**(source.get("raw") or {}), **(dest.get("raw") or {})}
    dest["touches"] = list(dest.get("touches") or []) + list(source.get("touches") or [])
    dest["mergedFrom"] = list(dest.get("mergedFrom") or []) + [source_id]
    dest["updatedAt"] = board_store.now_iso()
    board_store.put_prospect(table, dest)
    _index_keys(table, dest)
    source["stage"] = "suppressed"
    source["suppressReason"] = f"merged into {into_id}"
    source["updatedAt"] = dest["updatedAt"]
    board_store.put_prospect(table, source)
    _index_keys(table, dest)
    return dest


def owner_put(table: Any, prospect_id: str, body: dict[str, Any]) -> dict[str, Any]:
    row = board_store.get_prospect(table, prospect_id)
    if not row:
        raise KeyError("prospect not found")
    if "stage" in body:
        stage = str(body.get("stage") or "")
        if stage not in OWNER_STAGES:
            raise ProspectError(f"stage may only be set to {', '.join(sorted(OWNER_STAGES))}")
        row["stage"] = stage
    if "contact" in body:
        contact = board_pii.normalize_email(str(body.get("contact") or ""))
        row["contact"] = contact or None
        if contact:
            row["email"] = row.get("email") or contact
    if "type" in body:
        row["type"] = _valid_type(str(body.get("type") or ""))
    if "note" in body:
        row["ownerNote"] = str(body.get("note") or "")[:2000]
    row["updatedAt"] = board_store.now_iso()
    board_store.put_prospect(table, row)
    _index_keys(table, row)
    return row


def import_csv(table: Any, text: str, *, source: str = "owner") -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    updated = 0
    errors: list[str] = []
    for i, raw in enumerate(reader, start=1):
        if i > 500:
            errors.append("stopped at 500 rows")
            break
        try:
            _, was_new = upsert(
                table,
                name=str(raw.get("name") or ""),
                type=str(raw.get("type") or "provider"),
                district=str(raw.get("district") or ""),
                source=source,
                website=str(raw.get("website") or ""),
                email=str(raw.get("email") or ""),
                phone=str(raw.get("phone") or ""),
            )
        except ProspectError as exc:
            errors.append(f"row {i}: {exc}")
            continue
        if was_new:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated, "errors": errors}


def mask_row(table: Any, row: dict[str, Any]) -> dict[str, Any]:
    pseud = board_pii.Pseudonymizer(table)
    out = public_row(row)
    if out.get("email"):
        out["email"] = pseud.alias_for_address(str(out["email"]))
    if out.get("contact"):
        out["contact"] = pseud.alias_for_address(str(out["contact"]))
    if out.get("phone"):
        out["phone"] = pseud.alias_for("phone", str(out["phone"]))
    try:
        pseud.save()
    except Exception as exc:
        _log_event("warning", tag="board_prospect_mask_save_failed", error=str(exc)[:200])
    return out


def public_row(row: dict[str, Any], *, duplicates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "prospectId": row.get("prospectId"),
        "name": row.get("name"),
        "type": row.get("type"),
        "district": row.get("district"),
        "stage": row.get("stage"),
        "source": row.get("source"),
        "website": row.get("website"),
        "phone": row.get("phone"),
        "email": row.get("email"),
        "contact": row.get("contact"),
        "placeId": row.get("placeId"),
        "score": row.get("score"),
        "fitNote": row.get("fitNote"),
        "ownerNote": row.get("ownerNote"),
        "touches": row.get("touches") or [],
        "nextTouchAt": row.get("nextTouchAt"),
        "lastThreadId": row.get("lastThreadId"),
        "qualifiedAt": row.get("qualifiedAt"),
        "createdAt": row.get("createdAt"),
        "updatedAt": row.get("updatedAt"),
        "possibleDuplicates": duplicates if duplicates is not None else [],
    }


def list_for_api(
    table: Any,
    *,
    stage: str | None = None,
    ptype: str | None = None,
    district: str | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> dict[str, Any]:
    if stage and stage not in BOARD_STAFF_PROSPECT_STAGES:
        raise ProspectError(f"unknown stage {stage}")
    if stage:
        rows, next_cursor = board_store.list_prospects_page(table, stage, limit=limit, cursor=cursor)
    else:
        rows = board_store.list_prospects(table, None, limit=limit)
        next_cursor = None
    if ptype:
        rows = [r for r in rows if str(r.get("type") or "") == ptype]
    if district:
        rows = [r for r in rows if str(r.get("district") or "") == district]
    return {
        "prospects": [public_row(r) for r in rows[:limit]],
        "nextCursor": next_cursor,
    }


def needs_contact(table: Any, *, limit: int = 40) -> list[dict[str, Any]]:
    rows = [
        r
        for r in board_store.list_prospects(table, "qualified", limit=200)
        if not r.get("contact")
    ]
    return [public_row(r) for r in rows[:limit]]


def open_data_rows(table: Any, kind: str, district: str = "") -> list[dict[str, Any]]:
    kind = str(kind or "").strip().lower()
    if kind in {"fehd", "restaurant", "restaurants"}:
        payload = board_opendata.fehd_licensed_premises(table)
        mapped_type = "restaurant"
    elif kind in {"edb", "school", "schools"}:
        payload = board_opendata.edb_schools(table)
        mapped_type = "school"
    elif kind in {"lcsd", "venue", "venues"}:
        payload = board_opendata.lcsd_programmes(table)
        mapped_type = "venue"
    else:
        raise ProspectError("kind must be fehd, edb or lcsd")
    district_f = _district(district) if district else ""
    out: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        name = str(row.get("nameEn") or row.get("nameZh") or "")
        dist = _district(str(row.get("district") or ""), str(row.get("addressEn") or row.get("addressZh") or ""))
        if district_f and district_f != "unknown" and dist != district_f:
            continue
        out.append(
            {
                "name": name,
                "type": mapped_type,
                "district": dist,
                "address": row.get("addressEn") or row.get("addressZh") or "",
                "source": kind,
            }
        )
        if len(out) >= 40:
            break
    return out
