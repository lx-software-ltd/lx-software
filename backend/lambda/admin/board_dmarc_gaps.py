"""DMARC findings that become config gaps, and the fresh-summary hide set."""

from __future__ import annotations

from typing import Any


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _gap_rank(finding: dict[str, Any]) -> tuple[int, int]:
    """Prefer the last-24h source with the most DMARC failures, then the most messages."""
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
    incident = _as_int(evidence.get("quarantine")) + _as_int(evidence.get("reject")) + _as_int(evidence.get("bothFail"))
    return (incident, _as_int(evidence.get("count")))


def _dmarc_gaps(finding: dict[str, Any]) -> list[tuple[str, str]]:
    """Config-gap id and reason for one finding. Empty when the finding is not a gap."""
    import board_dmarc

    kind = finding.get("kind")
    evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
    if kind == "own_sender_failing":
        sender = str(evidence.get("sender") or "sender")
        ip = str(evidence.get("sourceIp") or "unknown ip")
        reason = (
            f"DMARC failure for known sender {sender} at {ip}: "
            f"dkim {evidence.get('dkim') or 'none'}, spf {evidence.get('spf') or 'none'}, "
            f"{_as_int(evidence.get('quarantine'))} quarantined, "
            f"{_as_int(evidence.get('reject'))} rejected, "
            f"{_as_int(evidence.get('bothFail'))} both-fail "
            f"of {_as_int(evidence.get('count'))} from this IP."
        )
        return [(f"dmarc:{sender}", reason)]
    if kind == "unknown_source_failing" and finding.get("severity") != "info":
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for domain in evidence.get("failedAuthDomains") or []:
            matched = board_dmarc._match_known(str(domain), set(board_dmarc.CONSUMER_MAIL_DOMAINS))
            if not matched or matched in seen:
                continue
            seen.add(matched)
            rows.append(
                (
                    f"dmarc:{matched}",
                    (
                        f"Auth domain {matched} failed DMARC and is not in settings.dmarc.knownSenderDomains. "
                        "Add it if this is mail you send from Gmail or iCloud; otherwise treat the source as spoofing."
                    ),
                )
            )
        return rows
    return []


def note(table: Any, findings: list[dict[str, Any]]) -> None:
    import board_duties

    active: dict[str, tuple[tuple[int, int], str]] = {}
    for finding in findings:
        rank = _gap_rank(finding)
        for gap_id, reason in _dmarc_gaps(finding):
            current = active.get(gap_id)
            if current is None or rank > current[0]:
                active[gap_id] = (rank, reason)
    for gap_id, (_rank, reason) in active.items():
        board_duties.note_config_gap(table, gap_id=gap_id, reason=reason)
    stale: set[str] = set()
    for row in board_duties.list_config_gaps(table):
        gap_id = str(row.get("gapId") or "")
        if gap_id.startswith("dmarc:") and gap_id not in active:
            stale.add(gap_id)
    for gap_id in stale:
        board_duties.clear_config_gap(table, gap_id)


def summary_gap_ids(table: Any) -> set[str] | None:
    """Gap ids a fresh enabled summary still reports.

    None means the caller must not hide cached ``dmarc:`` rows: the summary is
    missing, stale, disabled, or long enough that a real finding may have been capped.
    """
    import board_dmarc

    payload = board_dmarc.read_summary(table)
    if not isinstance(payload, dict) or not payload.get("generatedAt"):
        return None
    if payload.get("enabled") is False or board_dmarc.summary_is_stale(payload):
        return None
    findings = [row for row in (payload.get("findings") or []) if isinstance(row, dict)]
    if len(findings) >= board_dmarc.SUMMARY_FINDING_CAP:
        return None
    active: set[str] = set()
    for finding in findings:
        for gap_id, _reason in _dmarc_gaps(finding):
            active.add(gap_id)
    return active
