"""Outreach sequence templates and due-touch selection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import board_hk
import board_store
from contract_constants import BOARD_STAFF_OUTREACH_SEQUENCE_DAYS, BOARD_STAFF_PROSPECT_TYPES

FOOTER_EN = (
    "You are receiving this because {name} is publicly listed as a children's "
    "activity provider in Hong Kong. Reply \"unsubscribe\" or use {unsubscribeUrl} "
    "and we will not write again."
)
FOOTER_ZH = (
    "你收到這封信，是因為 {name} 在香港公開列為兒童活動機構。"
    "回覆「退訂」或使用 {unsubscribeUrl}，我們不會再寫信。"
)

_WHO_EN = (
    "Siu Tin Dei is a Hong Kong directory of child-friendly activities for parents "
    "of children aged 0–12. We list venues and providers so families can find a class nearby."
)
_WHO_ZH = (
    "小天地是香港的兒童活動目錄，幫助 0 至 12 歲小朋友的家長找到附近的課堂和場地。"
)
_OFFER_EN = (
    "We are inviting selected organisations to a free listing at launch. There is no fee "
    "and we are not asking you to publish prices."
)
_OFFER_ZH = "我們正邀請合適的機構在推出時免費上架。沒有收費，也不需要公開價錢。"
_ASK_EN = "If this sounds useful, reply to this email or open the provider sign-up page: {signupUrl}"
_ASK_ZH = "若合適，請回覆這封電郵，或開啟機構登記頁：{signupUrl}"
_SIGN_EN = "Thank you,\nPartnerships\nSiu Tin Dei"
_SIGN_ZH = "謝謝\n合作夥伴\n小天地"


def _step(day: int, subject_en: str, subject_zh: str, why_en: str, why_zh: str) -> dict[str, Any]:
    body_en = "\n\n".join([_WHO_EN, why_en, _OFFER_EN, _ASK_EN, _SIGN_EN, FOOTER_EN])
    body_zh = "\n\n".join([_WHO_ZH, why_zh, _OFFER_ZH, _ASK_ZH, _SIGN_ZH, FOOTER_ZH])
    return {
        "dayOffset": day,
        "subjectEn": subject_en,
        "subjectZh": subject_zh,
        "bodyEn": body_en,
        "bodyZh": body_zh,
    }


def default_steps() -> list[dict[str, Any]]:
    days = list(BOARD_STAFF_OUTREACH_SEQUENCE_DAYS) or [0, 4, 10]
    while len(days) < 3:
        days.append(days[-1] + 4)
    return [
        _step(
            int(days[0]),
            "A free listing for {name} on Siu Tin Dei",
            "邀請 {name} 免費登上小天地",
            "We wrote because {fitNote}",
            "我們寫信，是因為 {fitNote}",
        ),
        _step(
            int(days[1]),
            "Following up: {name} on Siu Tin Dei",
            "跟進：{name} 與小天地",
            "A short follow-up — {fitNote}",
            "簡單跟進 — {fitNote}",
        ),
        _step(
            int(days[2]),
            "Last note about listing {name}",
            "最後一次關於 {name} 上架",
            "This is our last outreach. {fitNote}",
            "這是最後一次聯絡。{fitNote}",
        ),
    ]


def default_sequence(ptype: str) -> dict[str, Any]:
    return {"type": ptype, "steps": default_steps()}


def get_or_default(table: Any, ptype: str) -> dict[str, Any]:
    stored = board_store.get_sequence(table, ptype)
    if stored and isinstance(stored.get("steps"), list) and stored["steps"]:
        return stored
    return default_sequence(ptype)


def save(table: Any, ptype: str, body: dict[str, Any]) -> dict[str, Any]:
    if ptype not in BOARD_STAFF_PROSPECT_TYPES:
        raise ValueError(f"unknown sequence type {ptype}")
    steps_in = body.get("steps")
    if not isinstance(steps_in, list) or not steps_in:
        raise ValueError("steps must be a non-empty list")
    steps: list[dict[str, Any]] = []
    for raw in steps_in[:6]:
        if not isinstance(raw, dict):
            continue
        try:
            offset = int(raw.get("dayOffset"))
        except (TypeError, ValueError):
            continue
        steps.append(
            {
                "dayOffset": max(0, min(60, offset)),
                "subjectEn": str(raw.get("subjectEn") or "")[:200],
                "subjectZh": str(raw.get("subjectZh") or "")[:200],
                "bodyEn": str(raw.get("bodyEn") or "")[:8000],
                "bodyZh": str(raw.get("bodyZh") or "")[:8000],
            }
        )
    if not steps:
        raise ValueError("steps must include at least one valid step")
    doc = {"type": ptype, "steps": steps, "updatedAt": board_store.now_iso()}
    board_store.put_sequence(table, ptype, doc)
    return doc


def start(table: Any, prospect: dict[str, Any]) -> dict[str, Any]:
    now = board_store.now_iso()
    prospect["stage"] = "contacted"
    prospect["sequenceStartedAt"] = now
    prospect["nextTouchAt"] = now
    prospect["touches"] = list(prospect.get("touches") or [])
    prospect["updatedAt"] = now
    board_store.put_prospect(table, prospect)
    return prospect


def due(table: Any, now: str) -> list[dict[str, Any]]:
    rows = board_store.list_prospects(table, "contacted", limit=400)
    return [r for r in rows if str(r.get("nextTouchAt") or "") <= now]


def next_touch_at(started_iso: str, day_offset: int) -> str:
    started = board_hk.parse_iso(started_iso) if started_iso else datetime.now()
    local = board_hk.as_hkt(started)
    day = local.date() + timedelta(days=max(0, int(day_offset)))
    slot = datetime(day.year, day.month, day.day, 10, 0, tzinfo=board_hk.HKT)
    return board_hk.to_iso(slot)


def touch(table: Any, settings: dict[str, Any], prospect: dict[str, Any], *, personalisation: str = "") -> dict[str, Any]:
    """Build and send (or hold) the next sequence step via ``outreach_send``."""
    import board_outreach

    return board_outreach.send(
        table,
        settings,
        prospect_id=str(prospect.get("prospectId") or ""),
        step_index=len(prospect.get("touches") or []),
        personalisation=personalisation,
    )
