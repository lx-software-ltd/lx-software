"""Stable pseudonyms for contact details before text reaches the model.

Parents and providers write to ``siutindei.com`` with their names, email
addresses and phone numbers. The board only ever sees ``contact#17`` /
``phone#4`` style aliases; the owner sees the real values in the admin SPA
and in approval payloads. Aliases are stable across messages so a persona
can say "contact#17 wrote twice this week" and the owner can resolve it.

The alias map is one DynamoDB item (``BOARD#<b>#mail#pii`` / ``STATE``);
the board handles at most a few thousand contacts, well under the item cap.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import board_store

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# International numbers with a leading +, or Hong Kong 8-digit local numbers
# (first digit 2-9, optional space or dash in the middle).
PHONE_RE = re.compile(r"(?<![\w+])(?:\+\d[\d\s\-()]{6,16}\d|[2-9]\d{3}[ \-]?\d{4})(?![\w])")
ALIAS_RE = re.compile(r"\b(contact|phone)#(\d+)\b")

PII_STATE_SUFFIX = "mail#pii"


def _digest(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:24]


def normalize_email(value: str) -> str:
    return " ".join(str(value or "").split()).strip().strip("<>").lower()


def normalize_phone(value: str) -> str:
    digits = re.sub(r"[^\d+]", "", str(value or ""))
    return digits


def is_own_address(address: str, own_domains: set[str]) -> bool:
    addr = normalize_email(address)
    return "@" in addr and addr.rsplit("@", 1)[1] in own_domains


class Pseudonymizer:
    """Lazy-loading alias map. Call :meth:`save` after masking new values."""

    SAVE_RETRIES = 3

    def __init__(self, table: Any, *, own_domains: set[str] | None = None) -> None:
        self.table = table
        self.own_domains = {d.lower() for d in (own_domains or set())}
        self._state: dict[str, Any] | None = None
        self._dirty = False
        # ``next`` as loaded from storage (None = no item yet); the save condition.
        self._base_next: int | None = None
        # Aliases allocated locally since the last load, for merging on conflict.
        self._pending: dict[str, tuple[str, dict[str, Any]]] = {}

    # -- persistence --------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        stored = board_store._get_state(self.table, PII_STATE_SUFFIX) or {}
        self._base_next = int(stored["next"]) if stored.get("next") is not None else None
        return {
            "next": int(stored.get("next") or 1),
            "byDigest": dict(stored.get("byDigest") or {}),
            "byAlias": dict(stored.get("byAlias") or {}),
        }

    @property
    def state(self) -> dict[str, Any]:
        if self._state is None:
            self._state = self._load()
        return self._state

    def save(self) -> None:
        """Persist new aliases without clobbering a concurrent writer's map.

        The put is conditional on the stored ``next`` counter being the one we
        loaded. On conflict the remote map is reloaded and our new aliases are
        merged into it (remote wins for a digest both sides aliased; our alias
        is kept as a secondary key so text already produced still resolves).
        """
        if not self._dirty or self._state is None:
            return
        for attempt in range(self.SAVE_RETRIES + 1):
            doc = {**self._state, "updatedAt": board_store.now_iso()}
            if board_store._put_state_if_version(
                self.table, PII_STATE_SUFFIX, doc, attr="next", expected=self._base_next
            ):
                self._dirty = False
                self._base_next = int(self._state["next"])
                self._pending = {}
                return
            if attempt == self.SAVE_RETRIES:
                raise RuntimeError("pseudonym map save conflicted repeatedly")
            self._merge_remote()

    def _merge_remote(self) -> None:
        remote = self._load()
        by_digest = remote["byDigest"]
        by_alias = remote["byAlias"]
        next_n = int(remote["next"])
        for digest, (alias, entry) in self._pending.items():
            if digest in by_digest:
                by_alias.setdefault(alias, entry)
                continue
            if alias in by_alias and by_alias[alias] != entry:
                alias = f"{entry['kind']}#{next_n}"
                next_n += 1
            by_digest[digest] = alias
            by_alias[alias] = entry
            next_n = max(next_n, int(alias.rsplit("#", 1)[1]) + 1)
        remote["next"] = max(next_n, int(self._state["next"]) if self._state else 1)
        self._state = remote

    # -- aliases ------------------------------------------------------------

    def _allocate(self, kind: str, digest: str, entry: dict[str, Any]) -> str:
        alias = self.state["byDigest"].get(digest)
        if alias:
            return str(alias)
        alias = f"{kind}#{self.state['next']}"
        self.state["next"] += 1
        self.state["byDigest"][digest] = alias
        self.state["byAlias"][alias] = entry
        self._pending[digest] = (alias, entry)
        self._dirty = True
        return alias

    def alias_for(self, kind: str, value: str) -> str:
        normalized = normalize_email(value) if kind == "contact" else normalize_phone(value)
        if not normalized:
            return value
        return self._allocate(kind, _digest(kind, normalized), {"kind": kind, "value": normalized})

    def alias_for_external(self, namespace: str, external_id: str, *, display: str = "") -> str:
        """``contact#N`` for a third-party user id (e.g. a Facebook commenter).

        The alias is keyed on ``namespace:id`` so it is stable across reads even
        when the platform shows a different display name; the name is stored
        only for the owner-side resolve.
        """
        ident = str(external_id or "").strip()
        if not ident:
            return "contact#unknown"
        key = f"{namespace}:{ident}"
        entry = {"kind": "contact", "value": (display or key)[:120], "externalId": key}
        return self._allocate("contact", _digest("contact", key), entry)

    def alias_for_address(self, address: str) -> str:
        """Own-domain mailboxes stay visible; everyone else becomes ``contact#N``."""
        addr = normalize_email(address)
        if not addr or is_own_address(addr, self.own_domains):
            return addr
        return self.alias_for("contact", addr)

    def resolve(self, alias_or_value: str) -> str | None:
        """Return the real value for an alias, or the input if it is already a value."""
        text = str(alias_or_value or "").strip()
        m = ALIAS_RE.fullmatch(text)
        if not m:
            return text or None
        entry = self.state["byAlias"].get(text)
        return str(entry.get("value")) if isinstance(entry, dict) else None

    def is_known_contact(self, alias_or_value: str) -> bool:
        """True for a stored alias, an already-mapped address, or an own-domain mailbox."""
        text = str(alias_or_value or "").strip()
        if not text:
            return False
        if ALIAS_RE.fullmatch(text):
            return isinstance(self.state["byAlias"].get(text), dict)
        addr = normalize_email(text)
        if not addr:
            return False
        if is_own_address(addr, self.own_domains):
            return True
        return _digest("contact", addr) in self.state["byDigest"]

    # -- text ---------------------------------------------------------------

    def mask_text(self, text: str) -> str:
        if not text:
            return ""

        def _email(m: re.Match[str]) -> str:
            return self.alias_for_address(m.group(0))

        def _phone(m: re.Match[str]) -> str:
            return self.alias_for("phone", m.group(0))

        out = EMAIL_RE.sub(_email, text)
        return PHONE_RE.sub(_phone, out)

    def unmask_text(self, text: str) -> str:
        if not text:
            return ""
        return ALIAS_RE.sub(lambda m: self.resolve(m.group(0)) or m.group(0), text)
