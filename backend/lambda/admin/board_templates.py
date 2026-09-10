"""Hard-coded reply templates for WP3. Owner-editable later."""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, str]] = {
    "ack_escalation": {
        "en": (
            "Thank you for writing to Siu Tin Dei. We have received your message and a person "
            "on the team will follow up shortly. We have not made any decision yet.\n\n"
            "The siutindei team"
        ),
        "zh-HK": (
            "多謝來信。我們已收到你的訊息，同事會盡快跟進，現階段未有任何決定。\n\n"
            "小天地團隊"
        ),
    },
    "payment_dispute": {
        "en": (
            "Thank you for telling us about the payment. We have logged this for a person to review. "
            "Please do not send card details here.\n\nThe siutindei team"
        ),
        "zh-HK": (
            "多謝告知付款事宜。我們已交由同事覆核，請勿在此傳送信用卡資料。\n\n小天地團隊"
        ),
    },
    "cancellation": {
        "en": (
            "Thank you for writing about the booking. A person on the team will confirm what we can do "
            "and write back. We have not cancelled or changed anything yet.\n\nThe siutindei team"
        ),
        "zh-HK": (
            "多謝來信。同事會確認可如何處理後回覆你，現階段未有取消或更改任何預約。\n\n小天地團隊"
        ),
    },
    "safeguarding": {
        "en": (
            "Thank you for telling us. A person on the team will read this carefully and follow up. "
            "If anyone is in immediate danger, please contact the emergency services.\n\nThe siutindei team"
        ),
        "zh-HK": (
            "多謝告知。同事會仔細閱讀並跟進。如有人正面對即時危險，請先聯絡緊急服務。\n\n小天地團隊"
        ),
    },
    "data_request": {
        "en": (
            "Thank you for your data request. A person on the team will handle it under our privacy process "
            "and write back.\n\nThe siutindei team"
        ),
        "zh-HK": (
            "多謝你的資料要求。同事會按私隱程序處理並回覆。\n\n小天地團隊"
        ),
    },
}


def render(template_id: str, lang: str, **placeholders: Any) -> str:
    row = TEMPLATES.get(template_id) or {}
    text = row.get(lang) or row.get("en") or ""
    for key, value in placeholders.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def pick_lang(text: str) -> str:
    return "zh-HK" if any("\u4e00" <= ch <= "\u9fff" for ch in text or "") else "en"
