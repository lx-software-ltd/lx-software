"""Split ``receivables.sql`` into Data API ExecuteStatement payloads.

The RDS Data API runs one statement at a time and has no session, so
``BEGIN`` / ``COMMIT`` are dropped. Dollar-quoted ``DO $$ … $$`` blocks stay
together.
"""

from __future__ import annotations

import re
from pathlib import Path

_SKIP_HEAD = re.compile(r"^(begin|commit|end)\s*;?\s*$", re.IGNORECASE)


def candidate_sql_paths(module_file: str | Path = __file__) -> tuple[Path, ...]:
    """Packaged copy first, then the repo source when running from a checkout.

    Never index ``parents`` directly: inside Lambda the module lives at
    ``/var/task/sql_split.py`` and only has three parents.
    """
    here = Path(module_file).resolve()
    candidates = [here.with_name("receivables.sql")]
    repo_root = here.parents[3] if len(here.parents) > 3 else None
    if repo_root is not None:
        candidates.append(repo_root / "scripts" / "siutindei" / "receivables.sql")
    return tuple(candidates)


def load_receivables_sql() -> str:
    for path in candidate_sql_paths():
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError("receivables.sql not packaged next to sql_split.py")


def split_sql(sql: str) -> list[str]:
    """Return executable statements, preserving dollar-quoted bodies."""
    out: list[str] = []
    buf: list[str] = []
    dollar: str | None = None
    for raw_line in sql.splitlines():
        line = raw_line
        if dollar is None:
            stripped = line.split("--", 1)[0]
        else:
            stripped = line
        buf.append(stripped)
        i = 0
        text = stripped
        while i < len(text):
            if dollar:
                end = text.find(dollar, i)
                if end < 0:
                    break
                i = end + len(dollar)
                dollar = None
                continue
            if text[i] == "'":
                nxt = text.find("'", i + 1)
                i = len(text) if nxt < 0 else nxt + 1
                continue
            if text.startswith("$$", i):
                dollar = "$$"
                i += 2
                continue
            tag = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$", text[i:])
            if tag:
                dollar = tag.group(0)
                i += len(dollar)
                continue
            if text[i] == ";" and dollar is None:
                stmt = _normalize("".join(buf)[: -(len(text) - i)])
                buf = [text[i + 1 :]]
                if stmt:
                    out.append(stmt)
                text = text[i + 1 :]
                i = 0
                continue
            i += 1
    tail = _normalize("".join(buf))
    if tail:
        out.append(tail)
    return out


def _normalize(chunk: str) -> str:
    stmt = "\n".join(line.rstrip() for line in chunk.splitlines()).strip()
    if not stmt or _SKIP_HEAD.match(stmt):
        return ""
    return stmt


def receivables_statements() -> list[str]:
    return split_sql(load_receivables_sql())
