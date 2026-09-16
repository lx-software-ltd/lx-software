"""Engineering runner: dispatch Cursor-on-Actions, review PRs, merge staging.

See docs/architecture/executive-board-autonomy-implementation.md WP10.
Workflows live in the siutindei repo (appendix A). This module only dispatches
and enforces policy.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from contract_constants import (
    BOARD_CODE_CI_FIX_MAX_ROUNDS,
    BOARD_CODE_REVIEW_MAX_ROUNDS,
    BOARD_CODE_RUN_COOLDOWN_SECONDS,
    BOARD_CODE_RUN_MAX_ROUNDS,
)

import board_github
import board_hk
import board_staff
import board_store
from http_common import _log_event

WORKFLOW_AGENT = "board-agent.yml"
WORKFLOW_MERGE = "board-merge-staging.yml"
WORKFLOW_PROMOTE = "board-promote.yml"
PROTECTED_DIR_NAMES = frozenset({"auth", "payments", "migrations"})
PROTECTED_ROOTS = frozenset({"infra", ".github"})
CONTENT_ROOT = "content"
LINE_LIMIT = 400
CONTENT_LINE_LIMIT = 2000
MAX_DIFF_CHARS = 30_000
MAX_OPEN_BOARD_PRS = 2
LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "npm-shrinkwrap.json",
        "poetry.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
        "pubspec.lock",
        "go.sum",
        "uv.lock",
        "flake.lock",
    }
)
_RUN_DONE = frozenset(
    {"completed", "failure", "cancelled", "timed_out", "startup_failure", "success", "skipped", "neutral"}
)
_RUN_FAILED = frozenset({"failure", "cancelled", "timed_out", "startup_failure"})
_RUN_WAITING_STATUS = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
KINDS = frozenset({"feature", "fix", "content"})
CI_OK = frozenset({"success", "neutral", "skipped"})
REVIEW_PENDING_GRACE_SECONDS = 60 * 60
_ISSUE_RE = re.compile(r"#(\d+)")
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
_RUN_INDEX = "code:runs"
_RUNNER_CAPS_KEY = "code:runner-caps"
_RUNNER_CAPS_TTL = 3600
_FAILURE_HISTORY_CAP = 6
_EXCERPT_MAX_CHARS = 2500
_BRIEF_DISPATCH_MAX = 6000
_FAILURE_LINE_RE = re.compile(
    r"(?:pull request changes \d+ lines|protected path \S+|content pull request changes \d+ lines"
    r"|error: .+|Failed .+|mypy:.+|got \".+\", expected \".+\")",
    re.I,
)
_PYTEST_LINE_RE = re.compile(r"^(?:FAILED |ERROR |E\s{2,})")
_POLICY_FAILURE_RE = re.compile(
    r"protected path |pull request changes \d+ lines|content pull request changes \d+ lines",
    re.I,
)
_LOG_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")
_YAML_REVISION_KEY_RE = re.compile(r"^[ \t]+(pr_number|ci_failure):(?:[ \t]|$)")
_CI_FIX_LOOKBACK_STATUSES = (
    "queued",
    "running",
    "waiting_approval",
    "review",
    "delivered",
    "needs_owner",
    "failed",
    "cancelled",
)
_PENDING_ONLY_RE = re.compile(
    r"\b(?:ci is pending|pending ci|ci.{0,24}pending|not ready for review yet as the ci)\b",
    re.I,
)
_ISSUE_TITLE_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "into",
        "issue",
        "board",
        "ready",
        "add",
        "fix",
        "update",
        "upgrade",
    }
)


class CodeError(ValueError):
    """Runner policy or GitHub dispatch failure."""


class CodeRefused(CodeError):
    """Policy guard: not a GitHub / runner failure. Recorded as ``refused``."""

    refused = True


def _repo() -> str:
    return board_github.repo_full_name()


def _gh(method: str, path: str, body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return board_github._request(method, path, body=body, **kwargs)  # noqa: SLF001


def _path_parts(path: str) -> list[str]:
    normalized = str(path or "").replace("\\", "/").lstrip("/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return [p for p in normalized.split("/") if p]


def path_is_protected(path: str) -> bool:
    parts = _path_parts(path)
    if not parts:
        return False
    if parts[0] in PROTECTED_ROOTS:
        return True
    return any(part in PROTECTED_DIR_NAMES for part in parts)


def path_is_content(path: str) -> bool:
    parts = _path_parts(path)
    return bool(parts) and parts[0] == CONTENT_ROOT


def file_paths(row: dict[str, Any]) -> list[str]:
    out = []
    for key in ("filename", "previous_filename"):
        value = str(row.get(key) or "").strip()
        if value:
            out.append(value)
    return out


def path_is_lockfile(path: str) -> bool:
    parts = _path_parts(path)
    return bool(parts) and parts[-1] in LOCKFILE_NAMES


def changed_lines(files: list[dict[str, Any]]) -> int:
    total = 0
    for row in files:
        if any(path_is_lockfile(path) for path in file_paths(row)):
            continue
        if row.get("changes") is not None:
            try:
                total += int(row.get("changes") or 0)
                continue
            except (TypeError, ValueError):
                pass
        try:
            total += int(row.get("additions") or 0) + int(row.get("deletions") or 0)
        except (TypeError, ValueError):
            continue
    return total


def files_protected(files: list[dict[str, Any]]) -> list[str]:
    hits: list[str] = []
    for row in files:
        for path in file_paths(row):
            if path_is_protected(path):
                hits.append(path)
    return hits


def files_outside_content(files: list[dict[str, Any]]) -> list[str]:
    return [path for row in files for path in file_paths(row) if not path_is_content(path)]


def dispatch_workflow(
    name: str, inputs: dict[str, Any], *, ref: str = "staging", table: Any = None
) -> dict[str, Any]:
    repo = _repo()
    payload = {"ref": ref, "inputs": {str(k): str(v) for k, v in inputs.items()}}
    try:
        _gh("POST", f"/repos/{repo}/actions/workflows/{name}/dispatches", payload)
    except board_github.GitHubSnapshotError as exc:
        if (
            getattr(exc, "status", None) == 422
            and "unexpected input" in str(exc).lower()
        ):
            if table is not None:
                board_store.put_cache(table, _RUNNER_CAPS_KEY, {"revision": False}, ttl_seconds=_RUNNER_CAPS_TTL)
            raise CodeRefused(
                "runner workflow rejected revision inputs; owner must apply the Appendix A revision patch"
            ) from exc
        raise
    return {"ok": True, "workflow": name, "ref": ref, "inputs": inputs}


def _run_index(table: Any) -> list[str]:
    hit = board_store.get_cache(table, _RUN_INDEX)
    if hit and isinstance(hit.get("payload"), dict):
        return [str(x) for x in (hit["payload"].get("ids") or []) if x]
    return []


def _save_run_index(table: Any, ids: list[str]) -> None:
    board_store.put_cache(table, _RUN_INDEX, {"ids": ids[:80]}, ttl_seconds=40 * 86400)


def _put_run(table: Any, task_id: str, payload: dict[str, Any]) -> None:
    board_store.put_cache(table, f"code:run:{task_id}", payload, ttl_seconds=40 * 86400)
    ids = _run_index(table)
    if task_id not in ids:
        _save_run_index(table, [task_id, *ids])


def _get_run(table: Any, task_id: str) -> dict[str, Any]:
    hit = board_store.get_cache(table, f"code:run:{task_id}")
    if hit and isinstance(hit.get("payload"), dict):
        return dict(hit["payload"])
    return {}


def list_open_board_prs() -> list[dict[str, Any]]:
    repo = _repo()
    raw = _gh("GET", f"/repos/{repo}/pulls?state=open&per_page=50") or []
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for pr in raw:
        if not isinstance(pr, dict):
            continue
        head = ((pr.get("head") or {}).get("ref") or "") if isinstance(pr.get("head"), dict) else ""
        if str(head).startswith("board/"):
            out.append(pr)
    return out


def _issue_from_pr(pr: dict[str, Any]) -> int | None:
    blob = f"{pr.get('title') or ''} {pr.get('body') or ''}"
    match = _ISSUE_RE.search(blob)
    if not match:
        return None
    return int(match.group(1))


def _run_in_flight(row: dict[str, Any]) -> bool:
    """True while a dispatched runner has neither a PR nor a terminal conclusion."""
    if not row or row.get("prNumber"):
        return False
    if row.get("failedAt"):
        return False
    status = str(row.get("runStatus") or "").lower()
    conclusion = str(row.get("conclusion") or "").lower()
    if conclusion == "action_required" or status in _RUN_WAITING_STATUS:
        return True
    if status == "completed" or conclusion in _RUN_DONE:
        return False
    return True


def issue_has_open_board_pr(issue_number: int, table: Any | None = None, *, except_task_id: str = "") -> bool:
    for pr in list_open_board_prs():
        if _issue_from_pr(pr) == issue_number:
            return True
    if table is not None:
        for task_id in _run_index(table):
            if except_task_id and task_id == except_task_id:
                continue
            row = _get_run(table, task_id)
            if int(row.get("issue") or 0) != issue_number:
                continue
            if _run_in_flight(row):
                return True
    return False


def _pr_for_branch(task_id: str) -> dict[str, Any] | None:
    repo = _repo()
    owner = repo.split("/", 1)[0]
    raw = _gh("GET", f"/repos/{repo}/pulls?head={owner}:board/{task_id}&state=all&per_page=5") or []
    if isinstance(raw, list) and raw:
        return raw[0] if isinstance(raw[0], dict) else None
    for pr in list_open_board_prs():
        head = ((pr.get("head") or {}).get("ref") or "") if isinstance(pr.get("head"), dict) else ""
        if head == f"board/{task_id}":
            return pr
    return None


def _runs_for_task(task_id: str) -> list[dict[str, Any]]:
    repo = _repo()
    raw = _gh("GET", f"/repos/{repo}/actions/runs?per_page=30") or {}
    runs = raw.get("workflow_runs") if isinstance(raw, dict) else raw
    out: list[dict[str, Any]] = []
    if not isinstance(runs, list):
        return out
    needle = str(task_id)
    for run in runs:
        if not isinstance(run, dict):
            continue
        blob = f"{run.get('name') or ''} {run.get('display_title') or ''} {run.get('displayTitle') or ''}"
        if needle in blob:
            out.append(run)
    return out


def reset_lookup_caches_for_tests() -> None:
    """Kept so runner tests can isolate GitHub lookups; no process cache remains."""
    return


def _lookup_issue(number: int) -> dict[str, Any]:
    """Fetch an issue. Empty dict on transport error so callers can fail open."""
    try:
        found = board_github.op_get_issue({"number": number})
    except Exception:
        return {}
    return found if isinstance(found, dict) else {}


def ci_state(sha: str) -> str:
    """Return ``success``, ``failure``, or ``pending`` for a head SHA."""
    if not sha:
        return "pending"
    repo = _repo()
    checks = _gh("GET", f"/repos/{repo}/commits/{sha}/check-runs") or {}
    runs = checks.get("check_runs") if isinstance(checks, dict) else None
    if isinstance(runs, list) and runs:
        items = [r for r in runs if isinstance(r, dict)]
        if any(str(r.get("status") or "") != "completed" for r in items):
            return "pending"
        if all(str(r.get("conclusion") or "") in CI_OK for r in items):
            return "success"
        return "failure"
    status = _gh("GET", f"/repos/{repo}/commits/{sha}/status") or {}
    state = str((status or {}).get("state") or "") if isinstance(status, dict) else ""
    if state == "success":
        return "success"
    if state in ("failure", "error"):
        return "failure"
    return "pending"


def ci_success(sha: str) -> bool:
    return ci_state(sha) == "success"


def _pr_files(number: int) -> list[dict[str, Any]]:
    repo = _repo()
    files: list[dict[str, Any]] = []
    page = 1
    while page <= 20:
        raw = _gh("GET", f"/repos/{repo}/pulls/{int(number)}/files?per_page=100&page={page}") or []
        batch = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    pr = _get_pr(number)
    changed = int(pr.get("changed_files") or 0)
    if changed and changed != len(files):
        raise CodeError("could not load every changed file")
    return files


def _get_pr(number: int) -> dict[str, Any]:
    repo = _repo()
    pr = _gh("GET", f"/repos/{repo}/pulls/{int(number)}")
    if not isinstance(pr, dict):
        raise CodeError(f"pull request #{number} not found")
    return pr


def _diff_text(number: int) -> str:
    repo = _repo()
    raw = board_github._request(  # noqa: SLF001
        "GET",
        f"/repos/{repo}/pulls/{int(number)}",
        accept="application/vnd.github.diff",
    )
    text = raw if isinstance(raw, str) else str(raw or "")
    if len(text) > MAX_DIFF_CHARS:
        return text[: MAX_DIFF_CHARS - 40].rstrip() + f"\n... [truncated, {len(text)} chars total]"
    return text


def review_bundle(pr_number: int) -> dict[str, Any]:
    pr = _get_pr(pr_number)
    files = _pr_files(pr_number)
    sha = str((pr.get("head") or {}).get("sha") or "")
    ci = ci_state(sha)
    return {
        "prNumber": int(pr_number),
        "title": pr.get("title"),
        "base": (pr.get("base") or {}).get("ref"),
        "head": (pr.get("head") or {}).get("ref"),
        "draft": bool(pr.get("draft")),
        "changedLines": changed_lines(files),
        "changedPaths": [str(f.get("filename") or "") for f in files],
        "protectedPaths": files_protected(files),
        "ci": "success" if ci == "success" else "pending_or_failed",
        "ciState": ci,
        "sha": sha,
        "state": pr.get("state") or "open",
        "merged": bool(pr.get("merged") or pr.get("merged_at")),
        "diff": _diff_text(pr_number),
        "url": pr.get("html_url"),
        "issue": _issue_from_pr(pr),
    }


def parse_review_verdict(text: str) -> dict[str, Any]:
    blob = text or ""
    match = _JSON_BLOCK.search(blob)
    raw = match.group(1) if match else blob.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        from openrouter_client import parse_json_object_text

        parsed = parse_json_object_text(blob)
    if not isinstance(parsed, dict):
        return {}
    verdict = str(parsed.get("verdict") or "").strip().lower()
    if verdict not in ("accept", "changes"):
        return {}
    notes = parsed.get("notes") if isinstance(parsed.get("notes"), list) else []
    return {"verdict": verdict, "notes": [str(n)[:400] for n in notes if n][:12]}


def _notes_are_pending_only(notes: list[str]) -> bool:
    text = " ".join(notes).strip()
    if not text:
        return False
    if not _PENDING_ONLY_RE.search(text):
        return False
    lowered = text.lower()
    return "fail" not in lowered and "error" not in lowered


def _find_task(table: Any, kind: str, event_id: str, *, statuses: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    wanted = statuses or ("queued", "running", "waiting_approval", "review", "delivered", "needs_owner")
    for status in wanted:
        for task in board_store.list_tasks(table, status, limit=200):
            ref = task.get("eventRef") or {}
            if ref.get("kind") == kind and str(ref.get("id") or "") == event_id:
                return task
    return None


def architect_accepted(table: Any, pr_number: int) -> bool:
    task = _find_task(
        table, "code-review", f"pr:{int(pr_number)}", statuses=("delivered", "needs_owner")
    )
    if not task:
        return False
    if str(task.get("status") or "") == "needs_owner":
        flags = {str(f) for f in (task.get("flags") or [])}
        if "salvaged" not in flags:
            return False
        reviews = board_store.list_task_reviews(table, str(task.get("taskId") or ""))
        if not any(str(r.get("verdict") or "").lower() == "accept" for r in reviews):
            return False
    text = board_staff.read_deliverable(task, limit=20_000)
    parsed = parse_review_verdict(text)
    if parsed.get("verdict") != "accept":
        return False
    accepted_sha = str((task.get("eventRef") or {}).get("headSha") or parsed.get("headSha") or "")
    try:
        current = str((_get_pr(pr_number).get("head") or {}).get("sha") or "")
    except (CodeError, board_github.GitHubSnapshotError):
        return False
    return bool(accepted_sha) and accepted_sha == current


TERMINAL_MERGE_REASONS = frozenset(
    {
        "pull request is already merged",
        "pull request is not open",
    }
)


def is_terminal_merge_reason(reason: str) -> bool:
    text = (reason or "").strip().lower()
    return any(known in text for known in TERMINAL_MERGE_REASONS)


def pr_not_mergeable_reason(number: int) -> str | None:
    """Return a refuse reason when the PR is merged or closed. None if unknown/open."""
    if number <= 0:
        return "prNumber is required"
    try:
        pr = _get_pr(number)
    except (CodeError, board_github.GitHubSnapshotError):
        return None
    if pr.get("merged") or pr.get("merged_at"):
        return "pull request is already merged"
    if str(pr.get("state") or "open").lower() != "open":
        return "pull request is not open"
    return None


def merge_guard(ctx: Any, args: dict[str, Any]) -> str | None:
    try:
        number = int(args.get("prNumber") or 0)
    except (TypeError, ValueError):
        return "prNumber is required"
    if number <= 0:
        return "prNumber is required"
    try:
        bundle = review_bundle(number)
    except (CodeError, board_github.GitHubSnapshotError) as exc:
        return str(exc)[:200]
    if str(bundle.get("base") or "") != "staging":
        return "base branch must be staging"
    if bundle.get("merged"):
        return "pull request is already merged"
    if str(bundle.get("state") or "open").lower() != "open":
        return "pull request is not open"
    if bundle.get("ci") != "success":
        return "CI is not green"
    if not architect_accepted(ctx.table, number):
        return "architect review has not accepted this pull request"
    kind = str(args.get("kind") or _kind_for_pr(ctx.table, number, bundle) or "feature")
    lines = int(bundle.get("changedLines") or 0)
    if kind == "content":
        extra = files_outside_content(_pr_files(number))
        if extra:
            return f"content kind may only change content/** ({extra[0]})"
        if lines > CONTENT_LINE_LIMIT:
            return f"content pull request changes {lines} lines (max {CONTENT_LINE_LIMIT})"
        return None
    protected = bundle.get("protectedPaths") or []
    if protected:
        return f"protected path {protected[0]}"
    if lines > LINE_LIMIT:
        return f"pull request changes {lines} lines (max {LINE_LIMIT})"
    return None


def _kind_for_pr(table: Any, pr_number: int, bundle: dict[str, Any]) -> str:
    head = str(bundle.get("head") or "")
    if head.startswith("board/"):
        row = _get_run(table, head.split("/", 1)[1])
        if row.get("kind"):
            return str(row["kind"])
    files = _pr_files(pr_number)
    if files and not files_outside_content(files):
        return "content"
    return "feature"


def validate_run_task(args: dict[str, Any], ctx: Any | None = None) -> str | None:
    """Refuse a runner dispatch that names a missing, closed, or PR-number issue."""
    try:
        issue = int(args.get("issueNumber") or 0)
    except (TypeError, ValueError):
        return "issueNumber is required"
    if issue <= 0:
        return "issueNumber is required"
    task = _calling_task(ctx) if ctx is not None else {}
    ref = task.get("eventRef") or {}
    try:
        pr_from_ref = int(ref.get("prNumber") or 0)
    except (TypeError, ValueError):
        pr_from_ref = 0
    if pr_from_ref and issue == pr_from_ref:
        stored_issue = 0
        if ctx is not None:
            _source, row = _run_for_pr(ctx.table, pr_from_ref)
            try:
                stored_issue = int(row.get("issue") or 0)
            except (TypeError, ValueError):
                stored_issue = 0
        if stored_issue > 0 and stored_issue != issue:
            # Engineer passed the PR number; _is_revision_dispatch remaps to the stored issue.
            return None
        return (
            f"#{issue} is the pull request. Pass the GitHub issue number it implements"
            + (f" (stored issue #{stored_issue})." if stored_issue else ".")
        )
    found = _lookup_issue(issue)
    if not found:
        return None
    if isinstance(found, dict) and found.get("error"):
        return str(found.get("error") or f"GitHub issue #{issue} was not found")
    if isinstance(found, dict) and found.get("isPullRequest"):
        hinted = int(ref.get("issueNumber") or 0) if ref else 0
        hint = f" Use issue #{hinted} from the task brief." if hinted else ""
        return (
            f"#{issue} is a pull request, not an issue. Pass the GitHub issue number "
            f"the PR implements, not the PR number.{hint}"
        )
    state = str((found or {}).get("state") or "").lower()
    if state and state != "open":
        return f"GitHub issue #{issue} is {state}, not open"
    return None


def _code_run_limits() -> tuple[int, int]:
    return int(BOARD_CODE_RUN_COOLDOWN_SECONDS), int(BOARD_CODE_RUN_MAX_ROUNDS)


def _parse_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _run_for_pr(table: Any, pr_number: int) -> tuple[str, dict[str, Any]]:
    for task_id in _run_index(table):
        row = _get_run(table, task_id)
        try:
            stored = int(row.get("prNumber") or 0)
        except (TypeError, ValueError):
            stored = 0
        if stored == pr_number:
            return task_id, row
    return "", {}


def _calling_task(ctx: Any) -> dict[str, Any]:
    task_id = str(getattr(ctx, "task_id", "") or "")
    if not task_id:
        return {}
    return board_store.get_task(ctx.table, task_id) or {}


def ensure_run_for_pr(table: Any, pr_number: int) -> tuple[str, dict[str, Any]]:
    """Return the run row for ``pr_number``, creating a stub from the live PR if needed."""
    source_id, row = _run_for_pr(table, pr_number)
    if source_id:
        return source_id, row
    try:
        pr = _get_pr(pr_number)
    except (CodeError, board_github.GitHubSnapshotError):
        return "", {}
    issue = _issue_from_pr(pr) or 0
    head = str((pr.get("head") or {}).get("ref") or "")
    task_id = head.split("/", 1)[1] if head.startswith("board/") else f"pr-{pr_number}"
    existing = _get_run(table, task_id)
    row = {
        **existing,
        "taskId": task_id,
        "prNumber": pr_number,
        "issue": existing.get("issue") or issue,
        "kind": existing.get("kind") or "feature",
        "prUrl": pr.get("html_url") or existing.get("prUrl"),
    }
    if str(pr.get("state") or "open").lower() == "open" and not (pr.get("merged") or pr.get("merged_at")):
        row["prState"] = "open"
        row["prMerged"] = False
    _put_run(table, task_id, row)
    return task_id, row


_OWNER_REVISION_PR_RE = re.compile(r"\bPR\s*#\s*(\d+)\b", re.IGNORECASE)
_OWNER_REVISION_ISSUE_RE = re.compile(
    r"\bissue(?:Number)?\s*[#:]\s*(\d+)\b", re.IGNORECASE
)
_ENGINEER_OWNER_SEATS = frozenset({"engineer-1", "engineer-2"})


def is_engineer_owner_seat(assignee: str) -> bool:
    return str(assignee or "") in _ENGINEER_OWNER_SEATS


def parse_owner_revision_mention(brief: str) -> tuple[int | None, int | None]:
    """Return ``(prNumber, issueNumber)`` hinted in an owner brief, if any."""
    text = str(brief or "")
    pr_match = _OWNER_REVISION_PR_RE.search(text)
    issue_match = _OWNER_REVISION_ISSUE_RE.search(text)
    pr_number = int(pr_match.group(1)) if pr_match else None
    issue_number = int(issue_match.group(1)) if issue_match else None
    if pr_number is not None and pr_number <= 0:
        pr_number = None
    if issue_number is not None and issue_number <= 0:
        issue_number = None
    return pr_number, issue_number


def append_owner_revision_brief(brief: str, event_ref: dict[str, Any] | None) -> str:
    """Tell an owner reopen to dispatch the runner, not invent GitHub writes."""
    text = str(brief or "").strip()
    if not event_ref or str(event_ref.get("kind") or "") != "code-implement":
        return text
    if "code_run_task" in text:
        return text
    try:
        pr_number = int(event_ref.get("prNumber") or 0)
    except (TypeError, ValueError):
        pr_number = 0
    try:
        issue_number = int(event_ref.get("issueNumber") or 0)
    except (TypeError, ValueError):
        issue_number = 0
    issue_number = issue_number or pr_number
    extra = (
        f" Call code_run_task ONCE with issueNumber={issue_number} and a brief that "
        f"fixes PR #{pr_number}, then call task_finish. Do not invent GitHub write "
        "tools or open a second pull request. The board polls CI for you."
    )
    return (text + extra)[:4000]


def owner_revision_ref(table: Any, pr_number: int, issue_number: Any = None) -> dict[str, Any]:
    """``eventRef`` so an owner-created task revises an existing board PR."""
    source_id, row = ensure_run_for_pr(table, pr_number)
    try:
        issue = int(issue_number if issue_number not in (None, "") else (row.get("issue") or 0))
    except (TypeError, ValueError):
        issue = 0
    if issue <= 0:
        raise CodeRefused(
            f"PR #{int(pr_number)} has no linked GitHub issue; pass issueNumber"
        )
    if source_id:
        if not row.get("issue"):
            row["issue"] = issue
        row["reviewRounds"] = 0
        row["ownerReopenedAt"] = board_store.now_iso()
        _put_run(table, source_id, row)
        # Owner reopen still needs the Appendix A revision patch. Clearing the
        # capability cache lets a just-applied YAML change be seen immediately
        # instead of waiting out a 1h revision=False pin.
        _clear_runner_caps(table)
    return {
        "kind": "code-implement",
        "id": f"pr:{int(pr_number)}:owner",
        "prNumber": int(pr_number),
        "issueNumber": issue,
        "sourceTaskId": source_id or None,
    }


def _is_revision_dispatch(ctx: Any, issue: int) -> tuple[str, dict[str, Any], int]:
    """Reuse the original runner task id when revising an open board PR.

    ``eventRef.prNumber`` is authoritative. A mismatched engineer ``issueNumber``
    (often the PR number) is remapped to the stored issue instead of opening a
    duplicate branch.
    """
    task = _calling_task(ctx)
    ref = task.get("eventRef") or {}
    if str(ref.get("kind") or "") != "code-implement":
        return "", {}, issue
    try:
        pr_number = int(ref.get("prNumber") or 0)
    except (TypeError, ValueError):
        pr_number = 0
    if pr_number <= 0:
        return "", {}, issue
    source_id, row = ensure_run_for_pr(ctx.table, pr_number)
    if not source_id:
        return "", {}, issue
    try:
        stored_issue = int(row.get("issue") or 0)
    except (TypeError, ValueError):
        stored_issue = 0
    if stored_issue:
        if stored_issue != issue:
            _log_event(
                "warning",
                tag="board_code_revision_issue_mismatch",
                prNumber=pr_number,
                storedIssue=stored_issue,
                givenIssue=issue,
            )
        return source_id, row, stored_issue
    if issue == pr_number:
        return source_id, row, 0
    row["issue"] = issue
    _put_run(ctx.table, source_id, row)
    return source_id, row, issue


def _issue_title_nouns(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{4,}", str(title or "").lower())
    return {w for w in words if w not in _ISSUE_TITLE_STOPWORDS}


def _brief_mismatches_issue(issue: int, brief: str) -> bool:
    """True when the dispatch brief shares no key nouns with the issue title."""
    if issue <= 0:
        return False
    found = _lookup_issue(issue)
    if not isinstance(found, dict) or found.get("error") or found.get("isPullRequest"):
        return False
    nouns = _issue_title_nouns(str(found.get("title") or ""))
    if not nouns:
        return False
    blob = str(brief or "").lower()
    return not any(word in blob for word in nouns)


def _strip_log_line(raw: str) -> str:
    text = _ANSI_RE.sub("", raw)
    return _LOG_TS_RE.sub("", text).strip()


def extract_failure_line(log: str) -> str:
    """Last pytest or policy / compiler line from a failed Actions job log."""
    last_policy = ""
    last_pytest = ""
    for raw in str(log or "").splitlines():
        line = _strip_log_line(raw)
        if not line:
            continue
        if _PYTEST_LINE_RE.match(line):
            last_pytest = line[:400]
        if _FAILURE_LINE_RE.search(line):
            last_policy = line[:400]
    return last_pytest or last_policy


def extract_failure_excerpt(log: str, *, max_chars: int = _EXCERPT_MAX_CHARS) -> str:
    """Pytest summary or last assertion block from a failed Actions job log."""
    lines = [_strip_log_line(raw) for raw in str(log or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    summary_idx = next((i for i, line in enumerate(lines) if "short test summary info" in line.lower()), None)
    if summary_idx is not None:
        block: list[str] = []
        for line in lines[summary_idx:]:
            block.append(line)
            lowered = line.lower()
            if line.startswith("=") and "failed" in lowered and summary_idx + len(block) > 1:
                break
            if len(block) >= 20:
                break
        return "\n".join(block)[:max_chars]
    failed = [line for line in lines if _PYTEST_LINE_RE.match(line)]
    errors = [line for line in lines if line.startswith("E ") or line.startswith("E\t")]
    parts = [*errors[-12:], *failed[-6:]]
    if parts:
        return "\n".join(parts)[:max_chars]
    return "\n".join(lines[-30:])[:max_chars]


def _decode_job_log(log: Any) -> str:
    if log is None:
        return ""
    if isinstance(log, (bytes, bytearray)):
        return bytes(log).decode("utf-8", errors="replace")
    return str(log)


def _failure_for_run(run: dict[str, Any]) -> dict[str, str]:
    empty = {"line": "", "excerpt": "", "job": ""}
    run_id = run.get("id") or run.get("databaseId")
    if not run_id:
        return empty
    repo = _repo()
    try:
        jobs = _gh("GET", f"/repos/{repo}/actions/runs/{int(run_id)}/jobs") or {}
    except (TypeError, ValueError, board_github.GitHubSnapshotError):
        return empty
    items = jobs.get("jobs") if isinstance(jobs, dict) else jobs
    if not isinstance(items, list):
        return empty
    for job in items:
        if not isinstance(job, dict):
            continue
        if str(job.get("conclusion") or "").lower() not in _RUN_FAILED:
            continue
        job_id = job.get("id")
        if not job_id:
            continue
        try:
            log = _gh(
                "GET",
                f"/repos/{repo}/actions/jobs/{int(job_id)}/logs",
                accept="application/vnd.github.raw",
            )
        except (TypeError, ValueError, board_github.GitHubSnapshotError):
            continue
        text = _decode_job_log(log)
        if not text:
            continue
        line = extract_failure_line(text)
        excerpt = extract_failure_excerpt(text)
        if line or excerpt:
            return {"line": line, "excerpt": excerpt, "job": str(job.get("name") or "")}
    return empty


def _failure_line_for_run(run: dict[str, Any]) -> str:
    return _failure_for_run(run).get("line") or ""


def _failure_for_sha(sha: str) -> dict[str, str]:
    """Last pytest / policy excerpt from failed PR CI jobs on this head SHA."""
    empty = {"line": "", "excerpt": "", "job": ""}
    if not sha:
        return empty
    repo = _repo()
    try:
        raw = _gh("GET", f"/repos/{repo}/actions/runs?head_sha={sha}&per_page=20") or {}
    except (TypeError, ValueError, board_github.GitHubSnapshotError):
        return empty
    runs = raw.get("workflow_runs") if isinstance(raw, dict) else raw
    if not isinstance(runs, list):
        return empty
    for run in runs:
        if not isinstance(run, dict):
            continue
        if str(run.get("conclusion") or "").lower() not in _RUN_FAILED:
            continue
        blob = f"{run.get('path') or ''} {run.get('name') or ''} {run.get('display_title') or ''}"
        if "board-agent" in blob.lower():
            continue
        found = _failure_for_run(run)
        if found.get("line") or found.get("excerpt"):
            return found
    return empty


def _failure_line_for_sha(sha: str) -> str:
    return _failure_for_sha(sha).get("line") or ""


def _workflow_yaml_has_revision_inputs(text: str) -> bool:
    """True when workflow_dispatch declares ``pr_number`` and ``ci_failure`` keys.

    Comments such as ``# pr_number:`` do not count.
    """
    keys: set[str] = set()
    for raw in str(text or "").splitlines():
        stripped = raw.split("#", 1)[0].rstrip()
        match = _YAML_REVISION_KEY_RE.match(stripped)
        if match:
            keys.add(match.group(1))
    return keys == {"pr_number", "ci_failure"}


def _clear_runner_caps(table: Any) -> None:
    """Drop the 1h revise-capability cache so the next dispatch re-reads YAML."""
    board_store.put_cache(table, _RUNNER_CAPS_KEY, {}, ttl_seconds=60)


def runner_supports_revision(table: Any) -> bool:
    """True when staging ``board-agent.yml`` declares revision inputs. Fail closed."""
    hit = board_store.get_cache(table, _RUNNER_CAPS_KEY)
    if hit and isinstance(hit.get("payload"), dict) and "revision" in hit["payload"]:
        return bool(hit["payload"]["revision"])
    repo = _repo()
    try:
        raw = _gh("GET", f"/repos/{repo}/contents/.github/workflows/{WORKFLOW_AGENT}?ref=staging") or {}
    except board_github.GitHubSnapshotError as exc:
        # 404: file is gone — cache the negative. Transport / rate-limit / 5xx
        # must not pin revision=False for an hour.
        if getattr(exc, "status", None) == 404:
            board_store.put_cache(table, _RUNNER_CAPS_KEY, {"revision": False}, ttl_seconds=_RUNNER_CAPS_TTL)
        return False
    content = ""
    if isinstance(raw, dict):
        encoded = str(raw.get("content") or "").replace("\n", "")
        try:
            content = base64.b64decode(encoded).decode("utf-8", errors="replace") if encoded else ""
        except Exception:
            content = ""
    ok = _workflow_yaml_has_revision_inputs(content)
    board_store.put_cache(table, _RUNNER_CAPS_KEY, {"revision": ok}, ttl_seconds=_RUNNER_CAPS_TTL)
    return ok


def cached_runner_revision(table: Any) -> bool | None:
    """Cached revise capability, or ``None`` if compile must not hit GitHub."""
    hit = board_store.get_cache(table, _RUNNER_CAPS_KEY)
    if not hit or not isinstance(hit.get("payload"), dict) or "revision" not in hit["payload"]:
        return None
    return bool(hit["payload"]["revision"])


def _original_brief(prior: dict[str, Any]) -> str:
    return str(prior.get("originalBrief") or prior.get("brief") or "").strip()


def _revision_dispatch_brief(
    prior: dict[str, Any], engineer_brief: str, round_n: int, pr_number: int
) -> str:
    """Compose the runner brief for this dispatch only. Never persist the result.

    The CI excerpt travels in the ``ci_failure`` input so it is not repeated here.
    """
    original = _original_brief(prior)
    parts: list[str] = []
    if original:
        parts.append(original)
    parts.append(f"REVISION round {round_n} for PR #{int(pr_number)}.")
    if engineer_brief:
        parts.append(f"Fix points: {engineer_brief}")
    return "\n\n".join(parts)


def op_run_task(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        issue = int(args.get("issueNumber") or 0)
    except (TypeError, ValueError):
        raise CodeRefused("issueNumber is required") from None
    if issue <= 0:
        raise CodeRefused("issueNumber is required")
    kind = str(args.get("kind") or "feature").strip().lower()
    if kind not in KINDS:
        raise CodeRefused("kind must be feature, fix or content")
    brief = str(args.get("brief") or "").strip()
    if not brief:
        raise CodeRefused("brief is required")
    revision_id, revision_row, issue = _is_revision_dispatch(ctx, issue)
    if revision_id and issue <= 0:
        raise CodeRefused(
            "this PR has no linked GitHub issue; pass the issue number the PR implements"
        )
    caller = str(getattr(ctx, "task_id", "") or "")
    if revision_id:
        if not runner_supports_revision(ctx.table):
            raise CodeRefused(
                "runner workflow cannot revise an existing PR yet; owner must apply the Appendix A revision patch"
            )
        task_id = revision_id
        prior = revision_row
    else:
        task_id = str(ctx.task_id or args.get("taskId") or board_store.new_id())
        prior = _get_run(ctx.table, task_id)
        # Same-task in-flight / cooldown / rounds are handled below. Exclude
        # this task's own run so those guards are not shadowed by the
        # one-open-PR-per-issue check.
        if issue_has_open_board_pr(issue, ctx.table, except_task_id=task_id):
            raise CodeRefused(
                f"an open board/* pull request already references #{issue}. "
                "Reuse that branch or close the PR before starting another run."
            )
    cooldown, max_rounds = _code_run_limits()
    same_staff_task = bool(caller) and str(prior.get("lastStaffTaskId") or "") == caller
    if same_staff_task or not revision_id:
        if "dispatchRounds" in prior:
            dispatch_rounds = int(prior.get("dispatchRounds") or 0)
        else:
            dispatch_rounds = int(prior.get("rounds") or 0)
    else:
        # New architect-created revise task: fresh dispatch budget on the
        # shared run row. codeReviewMaxRounds still caps revise cycles.
        dispatch_rounds = 0
    if dispatch_rounds >= max_rounds:
        raise CodeRefused("two runs already made for this task; report the failure")
    started = _parse_iso(str(prior.get("dispatchedAt") or ""))
    now = datetime.now(timezone.utc)
    if prior.get("dispatchedAt") and (_run_in_flight(prior) or dispatch_rounds > 0):
        if started is None or now - started < timedelta(seconds=cooldown):
            raise CodeRefused("a run for this task is already in flight — call code_get_run")
    inputs: dict[str, Any] = {
        "task_id": task_id,
        "issue": str(issue),
        "brief": brief[:_BRIEF_DISPATCH_MAX],
        "kind": kind,
    }
    if revision_id:
        try:
            pr_number = int(prior.get("prNumber") or 0)
        except (TypeError, ValueError):
            pr_number = 0
        revision_round = int(prior.get("revisionRounds") or 0) + 1
        inputs["brief"] = _revision_dispatch_brief(prior, brief, revision_round, pr_number)[:_BRIEF_DISPATCH_MAX]
        inputs["pr_number"] = str(pr_number)
        inputs["ci_failure"] = str(prior.get("failureExcerpt") or prior.get("failureLine") or "")[:_EXCERPT_MAX_CHARS]
        inputs["revision_round"] = str(revision_round)
    dispatched = dispatch_workflow(WORKFLOW_AGENT, inputs, ref="staging", table=ctx.table)
    stored_brief = _original_brief(prior) if revision_id else brief
    payload = {
        **prior,
        "taskId": task_id,
        "issue": issue,
        "kind": kind,
        "brief": stored_brief,
        "originalBrief": stored_brief,
        "dispatchBrief": inputs["brief"],
        "rounds": int(prior.get("rounds") or 0) + 1,
        "dispatchRounds": dispatch_rounds + 1,
        "lastStaffTaskId": caller or task_id,
        "dispatchedAt": board_store.now_iso(),
        "workflow": WORKFLOW_AGENT,
    }
    if revision_id:
        payload["revisionRounds"] = int(prior.get("revisionRounds") or 0) + 1
        caller_ref = (_calling_task(ctx) if ctx is not None else {}).get("eventRef") or {}
        if caller_ref.get("ciFix"):
            payload["ciFixRounds"] = int(prior.get("ciFixRounds") or 0) + 1
    mismatch = _brief_mismatches_issue(issue, brief)
    if mismatch:
        payload["briefMismatch"] = True
        task = _calling_task(ctx) if ctx is not None else {}
        if task and "brief_mismatch" not in {str(f) for f in (task.get("flags") or [])}:
            task["flags"] = [*(task.get("flags") or []), "brief_mismatch"]
            board_store.put_task(ctx.table, task)
    payload.pop("failedAt", None)
    payload.pop("conclusion", None)
    payload.pop("runStatus", None)
    payload.pop("failureLine", None)
    payload.pop("failureExcerpt", None)
    payload.pop("failureJob", None)
    payload.pop("failureLineSha", None)
    _put_run(ctx.table, task_id, payload)
    return {**dispatched, **payload}


def op_get_run(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("taskId") or ctx.task_id or "").strip()
    if not task_id:
        raise CodeError("taskId is required")
    stored = _get_run(ctx.table, task_id)
    had_stored = bool(stored)
    runs = _runs_for_task(task_id)
    latest = runs[0] if runs else {}
    pr = _pr_for_branch(task_id)
    out = {
        **stored,
        "taskId": task_id,
        "runStatus": latest.get("status") or stored.get("runStatus") or "unknown",
        "conclusion": latest.get("conclusion"),
        "runUrl": latest.get("html_url"),
        "runName": latest.get("name") or latest.get("display_title"),
        "prNumber": (pr or {}).get("number") or stored.get("prNumber"),
        "prUrl": (pr or {}).get("html_url"),
        "prDraft": (pr or {}).get("draft"),
    }
    if not had_stored:
        return out
    stored["runStatus"] = out["runStatus"]
    if out.get("conclusion"):
        stored["conclusion"] = out["conclusion"]
    if out.get("prNumber"):
        stored["prNumber"] = out["prNumber"]
        stored["prUrl"] = out.get("prUrl") or stored.get("prUrl")
    conclusion = str(out.get("conclusion") or "").lower()
    if stored.get("runStatus") == "completed" and not stored.get("prNumber") and conclusion in _RUN_FAILED:
        stored["failedAt"] = stored.get("failedAt") or board_store.now_iso()
    if isinstance(pr, dict):
        stored["prState"] = str(pr.get("state") or "open")
        stored["prMerged"] = bool(pr.get("merged") or pr.get("merged_at"))
    elif stored.get("prNumber"):
        try:
            looked = _get_pr(int(stored["prNumber"]))
        except (CodeError, board_github.GitHubSnapshotError, TypeError, ValueError):
            looked = {}
        if looked:
            stored["prState"] = str(looked.get("state") or "open")
            stored["prMerged"] = bool(looked.get("merged") or looked.get("merged_at"))
            pr = looked
    sha = ""
    if isinstance(pr, dict):
        head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
        sha = str((head or {}).get("sha") or "")
    prev_sha = str(stored.get("headSha") or "")
    if sha and prev_sha and prev_sha != sha:
        stored["prSeenAt"] = board_store.now_iso()
    elif out.get("prNumber") and not stored.get("prSeenAt"):
        stored["prSeenAt"] = board_store.now_iso()
    if sha:
        stored["ciState"] = ci_state(sha)
        stored["headSha"] = sha
        if stored.get("failureLineSha") and stored.get("failureLineSha") != sha:
            stored.pop("failureLine", None)
            stored.pop("failureExcerpt", None)
            stored.pop("failureJob", None)
            stored.pop("failureLineSha", None)
        if stored.get("ciState") == "failure" and stored.get("failureLineSha") != sha:
            found = _failure_for_sha(sha)
            stored["failureLine"] = found.get("line") or ""
            stored["failureExcerpt"] = found.get("excerpt") or ""
            stored["failureJob"] = found.get("job") or ""
            stored["failureLineSha"] = sha
            history = [row for row in (stored.get("failureHistory") or []) if isinstance(row, dict)]
            last = history[-1] if history else {}
            if last.get("sha") != sha or last.get("line") != stored["failureLine"]:
                history.append(
                    {
                        "sha": sha,
                        "line": stored["failureLine"],
                        "at": board_store.now_iso(),
                    }
                )
            stored["failureHistory"] = history[-_FAILURE_HISTORY_CAP:]
    if (
        conclusion in _RUN_FAILED
        and stored.get("ciState") != "failure"
        and not stored.get("failureLine")
    ):
        found = _failure_for_run(latest)
        stored["failureLine"] = found.get("line") or ""
        if found.get("excerpt"):
            stored["failureExcerpt"] = found["excerpt"]
        if found.get("job"):
            stored["failureJob"] = found["job"]
    if stored.get("failureLine"):
        out["failureLine"] = stored["failureLine"]
    if stored.get("failureExcerpt"):
        out["failureExcerpt"] = stored["failureExcerpt"]
    if stored.get("failureJob"):
        out["failureJob"] = stored["failureJob"]
    if stored.get("failureHistory"):
        out["failureHistory"] = stored["failureHistory"]
    if stored.get("ciFixRounds"):
        out["ciFixRounds"] = stored["ciFixRounds"]
    if stored.get("prSeenAt"):
        out["prSeenAt"] = stored["prSeenAt"]
    if stored.get("headSha"):
        out["headSha"] = stored["headSha"]
    if stored.get("ciState"):
        out["ciState"] = stored["ciState"]
    if stored.get("prState"):
        out["prState"] = stored["prState"]
    if stored.get("prMerged"):
        out["prMerged"] = True
    if stored.get("ownerReopenedAt"):
        out["ownerReopenedAt"] = stored["ownerReopenedAt"]
    if stored.get("briefMismatch"):
        out["briefMismatch"] = True
    _put_run(ctx.table, task_id, stored)
    return out


def op_review_pr(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        number = int(args.get("prNumber") or 0)
    except (TypeError, ValueError):
        raise CodeError("prNumber is required") from None
    if number <= 0:
        raise CodeError("prNumber is required")
    return review_bundle(number)


def op_merge_staging(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        number = int(args.get("prNumber") or 0)
    except (TypeError, ValueError):
        raise CodeError("prNumber is required") from None
    if number <= 0:
        raise CodeError("prNumber is required")
    reason = merge_guard(ctx, args)
    if reason:
        return {"error": reason}
    return dispatch_workflow(WORKFLOW_MERGE, {"pr_number": str(number)}, ref="staging")


def inspect_close_pr(args: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Return ``(reason, pr)``. ``reason`` is set when the PR must not be closed."""
    try:
        number = int(args.get("prNumber") or 0)
    except (TypeError, ValueError):
        return "prNumber is required", None
    if number <= 0:
        return "prNumber is required", None
    try:
        pr = _get_pr(number)
    except (CodeError, board_github.GitHubSnapshotError) as exc:
        return str(exc)[:200], None
    if pr.get("merged") or pr.get("merged_at"):
        return "pull request is already merged", pr
    head = str((pr.get("head") or {}).get("ref") or "")
    if not head.startswith("board/"):
        return "only board/* pull requests can be closed this way", pr
    if str((pr.get("base") or {}).get("ref") or "") != "staging":
        return "base branch must be staging", pr
    if str(pr.get("state") or "open").lower() != "open":
        return "pull request is not open", pr
    return None, pr


def close_guard(_ctx: Any, args: dict[str, Any]) -> str | None:
    """Refuse closing anything except an open, unmerged board/* PR into staging."""
    reason, _pr = inspect_close_pr(args)
    return reason


def preview_close_pr(_ctx: Any, args: dict[str, Any]) -> dict[str, Any] | None:
    reason, pr = inspect_close_pr(args)
    if reason or not pr:
        return None
    return {
        "prNumber": pr.get("number"),
        "title": pr.get("title"),
        "head": (pr.get("head") or {}).get("ref"),
        "base": (pr.get("base") or {}).get("ref"),
        "url": pr.get("html_url"),
        "reason": str(args.get("reason") or "")[:400],
    }


def _reject_pending_merge_approvals(table: Any, settings: dict[str, Any] | None, pr_number: int, note: str) -> int:
    """Drop stale merge proposals so a vetoed close cannot be merged afterwards."""
    rejected = 0
    now = board_store.now_iso()
    for approval in board_store.list_approvals(table):
        if approval.get("status") != "pending" or approval.get("op") != "code_merge_staging":
            continue
        try:
            if int((approval.get("arguments") or {}).get("prNumber") or 0) != pr_number:
                continue
        except (TypeError, ValueError):
            continue
        approval_id = str(approval.get("approvalId") or "")
        if not approval_id:
            continue
        if not board_store.claim_approval_decision(table, approval_id, status="rejected"):
            continue
        decided = {
            **approval,
            "status": "rejected",
            "note": note[:1000],
            "decidedAt": now,
            "decidedBySub": "system:close-pr",
            "updatedAt": now,
        }
        board_store.put_approval(table, decided)
        if settings is not None:
            try:
                board_staff.resume_after_approval(table, settings, decided)
            except Exception as exc:
                _log_event(
                    "warning",
                    tag="board_code_close_resume_failed",
                    approvalId=approval_id,
                    error=str(exc)[:200],
                )
        rejected += 1
    return rejected


def _issue_label_list(issue: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for lab in issue.get("labels") or []:
        text = str(lab.get("name") if isinstance(lab, dict) else lab or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def _abandon_linked_issue(pr: dict[str, Any], pr_number: int, reason: str) -> dict[str, Any]:
    """Stop the runner re-picking the issue: drop board-ready, add board-closed, comment."""
    out: dict[str, Any] = {"issue": None, "relabeled": False, "commented": False, "labels": []}
    issue = _issue_from_pr(pr)
    if not issue or issue == int(pr_number):
        return out
    out["issue"] = issue
    repo = _repo()
    try:
        raw = _gh("GET", f"/repos/{repo}/issues/{issue}")
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_close_issue_load_failed", issue=issue, error=str(exc)[:200])
        return out
    if not isinstance(raw, dict) or raw.get("pull_request"):
        return out
    kept = [name for name in _issue_label_list(raw) if name.lower() != BOARD_READY_LABEL]
    if not any(name.lower() == BOARD_CLOSED_LABEL for name in kept):
        kept.append(BOARD_CLOSED_LABEL)
    try:
        updated = _gh("PUT", f"/repos/{repo}/issues/{issue}/labels", {"labels": kept})
        if isinstance(updated, list):
            out["labels"] = [str(row.get("name") or "") for row in updated if isinstance(row, dict)]
        else:
            out["labels"] = kept
        out["relabeled"] = True
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_close_issue_label_failed", issue=issue, error=str(exc)[:200])
    try:
        board_github.op_comment_issue(
            {
                "number": issue,
                "body": (
                    f"Board PR #{pr_number} was closed without merging: {reason[:400]}. "
                    f"Removed `{BOARD_READY_LABEL}` and added `{BOARD_CLOSED_LABEL}` so the runner "
                    "will not pick this issue up again. Re-add board-ready to retry."
                ),
            }
        )
        out["commented"] = True
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_close_issue_comment_failed", issue=issue, error=str(exc)[:200])
    return out


def op_close_pr(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Close a board/* PR without merging. Does not delete the branch."""
    reason = str(args.get("reason") or "").strip()
    if not reason:
        raise CodeError("reason is required")
    blocked, pr = inspect_close_pr(args)
    if blocked or not pr:
        raise CodeError(blocked or "prNumber is required")
    number = int(pr.get("number") or args.get("prNumber") or 0)
    if not board_github.write_enabled():
        raise CodeError(
            "GitHub writes need a token: replace the dummy value in the "
            "lxsoftware-admin-siutindei-board-github-token secret with a fine-grained token "
            "that has issues: write and pull-requests: write on the repository"
        )
    updated = _gh("PATCH", f"/repos/{_repo()}/pulls/{number}", {"state": "closed"})
    if not isinstance(updated, dict) or str(updated.get("state") or "") != "closed":
        raise CodeError(f"GitHub did not close pull request #{number}")
    commented = False
    try:
        board_github.op_comment_issue(
            {"number": number, "body": f"Closed by the Executive Board: {reason[:400]}"}
        )
        commented = True
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_close_comment_failed", prNumber=number, error=str(exc)[:200])
    abandoned = _abandon_linked_issue(pr, number, reason)
    rejected = 0
    table = getattr(ctx, "table", None)
    if table is not None:
        rejected = _reject_pending_merge_approvals(
            table,
            getattr(ctx, "settings", None),
            number,
            f"PR #{number} was closed without merging: {reason[:200]}",
        )
    return {
        "ok": True,
        "prNumber": number,
        "state": "closed",
        "url": updated.get("html_url") or pr.get("html_url"),
        "head": (pr.get("head") or {}).get("ref"),
        "commented": commented,
        "rejectedMergeApprovals": rejected,
        "issue": abandoned.get("issue"),
        "issueRelabeled": bool(abandoned.get("relabeled")),
        "issueCommented": bool(abandoned.get("commented")),
    }


def compare_staging() -> dict[str, Any]:
    repo = _repo()
    raw = _gh("GET", f"/repos/{repo}/compare/main...staging") or {}
    if not isinstance(raw, dict):
        raw = {}
    commits = []
    for row in raw.get("commits") or []:
        if not isinstance(row, dict):
            continue
        commit = row.get("commit") or {}
        message = str((commit.get("message") or "")).splitlines()[0] if isinstance(commit, dict) else ""
        commits.append({"sha": str(row.get("sha") or "")[:8], "message": message[:160]})
    behind = int(raw.get("behind_by") or 0)
    ahead = int(raw.get("ahead_by") or 0)
    return {
        "status": raw.get("status") or "unknown",
        "behindBy": behind,
        "aheadBy": ahead,
        "commits": commits[:40],
        "canPromote": behind == 0 and ahead > 0,
        "htmlUrl": raw.get("html_url") or raw.get("permalink_url"),
    }


_SYNC_STAGING_CACHE = "duty:cto:sync-staging"
_SYNC_STAGING_EVENT_ID = "rebase-staging"
_DELEGATE_SEATS = ("architect", "engineer-1", "engineer-2")
_OPEN_SYNC_STATUSES = (
    "queued",
    "running",
    "waiting_approval",
    "waiting_subtask",
    "review",
    "needs_owner",
)


def _active_delegate_ids(table: Any, settings: dict[str, Any]) -> list[str]:
    roster = board_staff.seats_by_id(table, settings)
    return [seat_id for seat_id in _DELEGATE_SEATS if (roster.get(seat_id) or {}).get("isActive")]


def _sync_staging_brief(preview: dict[str, Any], delegates: list[str]) -> str:
    behind = int(preview.get("behindBy") or 0)
    ahead = int(preview.get("aheadBy") or 0)
    status = str(preview.get("status") or "unknown")
    url = str(preview.get("htmlUrl") or "").strip()
    compare = f" Compare: {url}." if url else ""
    if delegates:
        handoff = (
            "You may staff_assign this same brief to "
            + ", ".join(delegates)
            + " (your staff tool is propose by default, so that hand-off lands in Approvals "
            "unless the founder has given you act)."
        )
    else:
        handoff = (
            "No architect or engineer seat is active. Call code_sync_staging yourself or ask "
            "the founder to activate a seat."
        )
    diverge = ""
    if ahead and behind:
        diverge = (
            " Staging has commits that are not on main: rebase or merge, do not force-push "
            "those commits away."
        )
    return (
        f"siutindei staging is {behind} commit(s) behind main "
        f"(compare status={status}, aheadBy={ahead}).{compare}{diverge} "
        "You own keeping staging current with main so the promote path can run. "
        "Call code_sync_staging (merges main into staging; a propose-level call becomes an "
        "Approval, and act is a code_staging hold). Then call github_compare base=main "
        "head=staging and only task_finish when behindBy=0. github_list_commits without sha "
        "lists the default branch — do not use it to claim staging is current. "
        f"{handoff} "
        "Deliverable: markdown with behind/ahead counts from github_compare, the merge result, "
        "and the compare URL."
    )


def _ensure_rebase_task(
    table: Any,
    settings: dict[str, Any],
    preview: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if _find_task(table, "ops", _SYNC_STAGING_EVENT_ID, statuses=_OPEN_SYNC_STATUSES):
        return None
    snapshot = preview if isinstance(preview, dict) else staging_preview()
    if snapshot.get("error"):
        return None
    if int(snapshot.get("behindBy") or 0) <= 0:
        return None
    delegates = _active_delegate_ids(table, settings)
    try:
        return board_staff.create_task(
            table,
            settings,
            assignee="cto",
            origin="event",
            brief=_sync_staging_brief(snapshot, delegates)[:4000],
            deliverable_type="markdown",
            sla_hours=24,
            event_ref={"kind": "ops", "id": _SYNC_STAGING_EVENT_ID},
            created_by="board_code",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_code_rebase_skipped", error=str(exc)[:200])
        return None


def maybe_daily_staging_sync(
    table: Any, settings: dict[str, Any], preview: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Once per HKT day, open a CTO task when staging is behind main."""
    if not board_staff.enabled(settings):
        return None
    date_hkt = board_hk.today_hkt()
    hit = board_store.get_cache(table, _SYNC_STAGING_CACHE)
    payload = hit.get("payload") if isinstance(hit, dict) else None
    if isinstance(payload, dict) and payload.get("dateHkt") == date_hkt:
        return None
    preview = preview if isinstance(preview, dict) else staging_preview()
    if preview.get("error"):
        _log_event("warning", tag="board_code_staging_sync_preview_failed", error=str(preview.get("error"))[:200])
        return None
    if not board_store.claim_duty_marker(table, f"duty:cto:sync-staging:{date_hkt}"):
        return None
    behind = int(preview.get("behindBy") or 0)
    board_store.put_cache(
        table,
        _SYNC_STAGING_CACHE,
        {
            "dateHkt": date_hkt,
            "behindBy": behind,
            "aheadBy": int(preview.get("aheadBy") or 0),
            "status": preview.get("status") or "",
        },
        ttl_seconds=3 * 86400,
    )
    if behind <= 0:
        return None
    return _ensure_rebase_task(table, settings, preview=preview)


def op_promote(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or "production").strip() or "production"
    preview = compare_staging()
    if int(preview.get("behindBy") or 0) > 0:
        _ensure_rebase_task(ctx.table, ctx.settings, preview=preview)
        return {"error": "staging is behind main; rebase first", "preview": preview}
    dispatched = dispatch_workflow(WORKFLOW_PROMOTE, {"kind": kind}, ref="main")
    return {**dispatched, "preview": preview}


def staging_preview() -> dict[str, Any]:
    try:
        return compare_staging()
    except board_github.GitHubSnapshotError as exc:
        return {"error": str(exc)[:200], "commits": [], "canPromote": False, "behindBy": 0, "aheadBy": 0}


def staging_still_behind() -> dict[str, Any] | None:
    """Live compare used when accepting a sync-staging task. None means current."""
    preview = staging_preview()
    if preview.get("error") or int(preview.get("behindBy") or 0) > 0:
        return preview
    return None


_COMPARE_CACHE = "github:compare:main-staging"
_LABEL_CACHE = "github:label:board-ready"


def cache_staging_preview(table: Any, preview: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = dict(preview if isinstance(preview, dict) else staging_preview())
    snap["fetchedAt"] = board_store.now_iso()
    board_store.put_cache(table, _COMPARE_CACHE, snap, ttl_seconds=6 * 3600)
    return snap


def cached_staging_preview(table: Any) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, _COMPARE_CACHE)
    payload = hit.get("payload") if isinstance(hit, dict) else None
    return payload if isinstance(payload, dict) and payload else None


def queue_promote_approval(table: Any, settings: dict[str, Any], user_sub: str) -> dict[str, Any]:
    import board_tools

    preview = staging_preview()
    if preview.get("error"):
        raise CodeError(str(preview["error"]))
    if int(preview.get("behindBy") or 0) > 0:
        _ensure_rebase_task(table, settings, preview=preview)
        raise CodeError("staging is behind main; rebase first")
    ctx = board_tools.ToolContext(
        table=table,
        settings=settings,
        persona_id="cto",
        display_name="CTO",
        kind="schedule",
        actor="persona",
        owner_sub=user_sub,
    )
    approval = board_tools.create_approval(
        ctx,
        board_tools.REGISTRY["code_promote"],
        {"kind": "production", "reason": "Owner requested promote from the review page."},
        summary="Promote staging to main",
    )
    return {"approval": approval, "preview": preview}


def _run_pr_gone(state: dict[str, Any]) -> bool:
    if state.get("prMerged"):
        return True
    return str(state.get("prState") or "").lower() == "closed"


def _run_pr_prunable(state: dict[str, Any]) -> bool:
    """Drop merged PRs from the index. Closed-not-merged stay so a reopen can reuse the row."""
    return bool(state.get("prMerged"))


def _is_policy_failure(line: str) -> bool:
    return bool(_POLICY_FAILURE_RE.search(line or ""))


def _same_failure_twice(state: dict[str, Any]) -> bool:
    """True only after a dispatched ci-fix still produced the same failure line."""
    if int(state.get("ciFixRounds") or 0) < 1:
        return False
    history = [row for row in (state.get("failureHistory") or []) if isinstance(row, dict)]
    if len(history) < 2:
        return False
    left = str(history[-1].get("line") or "")
    right = str(history[-2].get("line") or "")
    return bool(left) and left == right


def _ci_fail_covers_sha(table: Any, pr_number: int, sha: str) -> bool:
    """Architect ``pr:{n}:ci-fail`` and engineer ci-fix must not share a SHA."""
    task = _find_task(table, "code-review", f"pr:{int(pr_number)}:ci-fail")
    if not task:
        return False
    stored = str((task.get("eventRef") or {}).get("headSha") or "")
    if stored:
        return stored == sha
    return str(task.get("status") or "") in (
        "queued",
        "running",
        "waiting_approval",
        "review",
        "needs_owner",
    )


def _ci_fix_skip_reason(table: Any, state: dict[str, Any]) -> str:
    try:
        issue = int(state.get("issue") or 0)
    except (TypeError, ValueError):
        issue = 0
    if issue <= 0:
        return " ci-fix skipped: no linked GitHub issue."
    line = str(state.get("failureLine") or "")
    if _is_policy_failure(line):
        return " ci-fix skipped: policy failure needs architect review."
    if int(state.get("ciFixRounds") or 0) >= BOARD_CODE_CI_FIX_MAX_ROUNDS:
        return " ci-fix exhausted."
    if not runner_supports_revision(table):
        return " runner cannot revise — apply the Appendix A revision patch."
    if _same_failure_twice(state):
        return " ci-fix skipped: same failure after the last fix."
    if not (state.get("failureExcerpt") or line):
        return " ci-fix skipped: no failure excerpt."
    return ""


def _maybe_ci_fix(
    table: Any, settings: dict[str, Any], task_id: str, state: dict[str, Any], engineer: str
) -> dict[str, Any] | None:
    if str(state.get("ciState") or "") != "failure":
        return None
    try:
        pr_number = int(state.get("prNumber") or 0)
        issue = int(state.get("issue") or 0)
    except (TypeError, ValueError):
        return None
    sha = str(state.get("headSha") or "")
    line = str(state.get("failureLine") or "").strip()
    excerpt = str(state.get("failureExcerpt") or "").strip()
    if pr_number <= 0 or not sha:
        return None
    if _ci_fix_skip_reason(table, state):
        return None
    if _ci_fail_covers_sha(table, pr_number, sha):
        return None
    event_id = f"pr:{pr_number}:ci:{sha[:7]}"
    if _find_task(table, "code-implement", event_id, statuses=_CI_FIX_LOOKBACK_STATUSES):
        return None
    job = str(state.get("failureJob") or "CI")
    brief = (
        f"CI on PR #{pr_number} failed at {job}. "
        f"Call code_run_task once with a brief that fixes exactly this:\n{excerpt or line}\n"
        "Do not restart the feature."
    )
    try:
        task = board_staff.create_task(
            table,
            settings,
            assignee=engineer,
            origin="event",
            brief=brief[:4000],
            deliverable_type="pr",
            sla_hours=12,
            event_ref={
                "kind": "code-implement",
                "id": event_id,
                "prNumber": pr_number,
                "issueNumber": issue,
                "ciFix": True,
                "taskId": task_id,
            },
            created_by="board_code",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_code_ci_fix_skipped", error=str(exc)[:200])
        return None
    return task


def poll_runs(table: Any, settings: dict[str, Any]) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    if not board_staff.enabled(settings):
        return created
    roster = board_staff.seats_by_id(table, settings)
    architect = "architect" if (roster.get("architect") or {}).get("isActive") else "cto"
    engineer = _pick_engineer(
        table, [sid for sid in ("engineer-1", "engineer-2") if (roster.get(sid) or {}).get("isActive")] or ["engineer-1"]
    )
    gone: set[str] = set()
    for task_id in _run_index(table):
        try:
            state = op_get_run(type("C", (), {"table": table, "task_id": task_id, "settings": settings})(), {"taskId": task_id})
        except (CodeError, board_github.GitHubSnapshotError) as exc:
            _log_event("warning", tag="board_code_poll_failed", taskId=task_id, error=str(exc)[:200])
            continue
        if _run_pr_gone(state):
            if _run_pr_prunable(state):
                gone.add(task_id)
            continue
        pr_number = state.get("prNumber")
        if not pr_number:
            continue
        ci = str(state.get("ciState") or "")
        pending_note = ""
        if ci == "pending":
            seen = _parse_iso(str(state.get("prSeenAt") or ""))
            now = datetime.now(timezone.utc)
            if seen is None or now - seen < timedelta(seconds=REVIEW_PENDING_GRACE_SECONDS):
                continue
            pending_note = " CI still pending after 60 min — review code only."
            event_id = f"pr:{int(pr_number)}:pending-ci"
        elif ci == "success":
            event_id = f"pr:{int(pr_number)}"
        elif ci == "failure":
            sha_prefix = str(state.get("headSha") or "")[:7]
            if sha_prefix and _find_task(
                table,
                "code-implement",
                f"pr:{int(pr_number)}:ci:{sha_prefix}",
                statuses=_CI_FIX_LOOKBACK_STATUSES,
            ):
                continue
            if _ci_fail_covers_sha(table, int(pr_number), str(state.get("headSha") or "")):
                continue
            fix = _maybe_ci_fix(table, settings, task_id, state, engineer)
            if fix:
                created.append(fix)
                continue
            event_id = f"pr:{int(pr_number)}:ci-fail"
            pending_note = _ci_fix_skip_reason(table, state)
        else:
            continue
        if _find_task(table, "code-review", event_id):
            continue
        failure_line = str(state.get("failureLine") or "").strip()
        mismatch = " The runner brief may not match the issue title (brief_mismatch)." if state.get("briefMismatch") else ""
        ci_note = f" CI failed: {failure_line}." if ci == "failure" and failure_line else ""
        try:
            task = board_staff.create_task(
                table,
                settings,
                assignee=architect,
                origin="event",
                brief=(
                    f"Review PR #{pr_number} ({state.get('runName') or task_id}). "
                    f"{ci_note}{pending_note}{mismatch} "
                    "Call code_review_pr and deliver Markdown that ends with "
                    '```json {"verdict":"accept"|"changes","notes":[…]}```'
                ),
                deliverable_type="markdown",
                sla_hours=24,
                event_ref={
                    "kind": "code-review",
                    "id": event_id,
                    "prNumber": int(pr_number),
                    "taskId": task_id,
                    "headSha": str(state.get("headSha") or ""),
                },
                created_by="board_code",
            )
            created.append(task)
        except board_staff.StaffError as exc:
            _log_event("info", tag="board_code_review_skipped", error=str(exc)[:200])
    if gone:
        current = _run_index(table)
        _save_run_index(table, [task_id for task_id in current if task_id not in gone])
    return created


def list_open_run_summaries(table: Any) -> list[dict[str, Any]]:
    """Table-only snapshot of indexed runs for the daily review. Never hits GitHub."""
    can_revise = cached_runner_revision(table)
    out: list[dict[str, Any]] = []
    for task_id in _run_index(table):
        row = _get_run(table, task_id)
        if not row.get("prNumber") or _run_pr_gone(row):
            continue
        out.append(
            {
                "taskId": task_id,
                "prNumber": row.get("prNumber"),
                "ciState": row.get("ciState") or "",
                "ciFixRounds": int(row.get("ciFixRounds") or 0),
                "ciFixMax": BOARD_CODE_CI_FIX_MAX_ROUNDS,
                "reviewRounds": int(row.get("reviewRounds") or 0),
                "reviewMax": BOARD_CODE_REVIEW_MAX_ROUNDS,
                "failureLine": row.get("failureLine") or "",
                "canRevise": can_revise,
            }
        )
    return out[:12]


_SKIP_ISSUE_LABELS = frozenset({"wontfix", "duplicate", "invalid", "board-closed"})
_IMPLEMENT_ISSUE_LABELS = frozenset(
    {"security", "high", "high-priority", "bug", "enhancement", "backend", "performance", "dependencies"}
)
_AUTO_FILED_TITLE_PREFIXES = ("NOTE:", "TODO:", "SECURITY NOTE:")
BOARD_READY_LABEL = "board-ready"
BOARD_CLOSED_LABEL = "board-closed"


def _issue_label_names(issue: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for lab in issue.get("labels") or []:
        if isinstance(lab, dict):
            names.add(str(lab.get("name") or "").strip().lower())
        elif isinstance(lab, str):
            names.add(lab.strip().lower())
    return {n for n in names if n}


def _issue_assignable(issue: dict[str, Any]) -> bool:
    if not isinstance(issue, dict) or issue.get("pull_request"):
        return False
    labels = _issue_label_names(issue)
    if labels & _SKIP_ISSUE_LABELS:
        return False
    title = str(issue.get("title") or "")
    if title.startswith(_AUTO_FILED_TITLE_PREFIXES):
        return False
    if BOARD_READY_LABEL in labels:
        return True
    if "documentation" in labels and not (labels & _IMPLEMENT_ISSUE_LABELS):
        return False
    return bool(labels & _IMPLEMENT_ISSUE_LABELS)


def ensure_board_ready_label(table: Any) -> None:
    hit = board_store.get_cache(table, _LABEL_CACHE)
    payload = hit.get("payload") if isinstance(hit, dict) else None
    if isinstance(payload, dict) and payload.get("exists") is True:
        return
    if isinstance(payload, dict) and payload.get("exists") is False:
        return
    repo = _repo()
    existing = _gh("GET", f"/repos/{repo}/labels/{BOARD_READY_LABEL}")
    if isinstance(existing, dict) and existing.get("name"):
        board_store.put_cache(table, _LABEL_CACHE, {"exists": True}, ttl_seconds=7 * 86400)
        return
    try:
        _gh(
            "POST",
            f"/repos/{repo}/labels",
            {
                "name": BOARD_READY_LABEL,
                "color": "0E8A16",
                "description": "Ready for an engineer to implement via code_run_task",
            },
        )
        board_store.put_cache(table, _LABEL_CACHE, {"exists": True}, ttl_seconds=7 * 86400)
    except board_github.GitHubSnapshotError as exc:
        board_store.put_cache(table, _LABEL_CACHE, {"exists": False}, ttl_seconds=86400)
        _log_event("info", tag="board_code_label_ensure_failed", error=str(exc)[:200])


def _add_board_ready_label(number: int) -> None:
    repo = _repo()
    try:
        _gh("POST", f"/repos/{repo}/issues/{int(number)}/labels", {"labels": [BOARD_READY_LABEL]})
    except board_github.GitHubSnapshotError as exc:
        _log_event("info", tag="board_code_label_issue_failed", issue=number, error=str(exc)[:200])


def _list_ready_issues() -> list[dict[str, Any]]:
    repo = _repo()
    labeled = _gh(
        "GET",
        f"/repos/{repo}/issues?state=open&labels={BOARD_READY_LABEL}&sort=created&direction=asc&per_page=20",
    ) or []
    ready = [i for i in labeled if isinstance(i, dict) and not i.get("pull_request")] if isinstance(labeled, list) else []
    if ready:
        return ready
    raw = _gh("GET", f"/repos/{repo}/issues?state=open&sort=created&direction=asc&per_page=50") or []
    if not isinstance(raw, list):
        return []
    return [i for i in raw if _issue_assignable(i)]


def maybe_assign_ready_issues(table: Any, settings: dict[str, Any]) -> list[dict[str, Any]]:
    if not board_staff.enabled(settings):
        return []
    try:
        open_prs = list_open_board_prs()
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_list_prs_failed", error=str(exc)[:200])
        return []
    if len(open_prs) >= MAX_OPEN_BOARD_PRS:
        return []
    try:
        ensure_board_ready_label(table)
        issues = _list_ready_issues()
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_list_issues_failed", error=str(exc)[:200])
        return []
    roster = board_staff.seats_by_id(table, settings)
    engineers = [sid for sid in ("engineer-1", "engineer-2") if (roster.get(sid) or {}).get("isActive")]
    if not engineers:
        return []
    created: list[dict[str, Any]] = []
    for issue in issues:
        number = int(issue.get("number") or 0)
        if number <= 0 or issue_has_open_board_pr(number, table):
            continue
        if _find_task(table, "code-implement", f"issue:{number}"):
            continue
        assignee = _pick_engineer(table, engineers)
        title = str(issue.get("title") or f"#{number}")
        try:
            task = board_staff.create_task(
                table,
                settings,
                assignee=assignee,
                origin="target",
                brief=(
                    f"Implement board-ready issue #{number}: {title}. "
                    f"Call code_run_task with issueNumber={number} and a concrete brief."
                ),
                deliverable_type="pr",
                sla_hours=48,
                event_ref={"kind": "code-implement", "id": f"issue:{number}", "issueNumber": number},
                created_by="board_code",
            )
            created.append(task)
            if BOARD_READY_LABEL not in _issue_label_names(issue):
                _add_board_ready_label(number)
        except board_staff.StaffError as exc:
            _log_event("info", tag="board_code_assign_skipped", error=str(exc)[:200])
            continue
        if len(open_prs) + len(created) >= MAX_OPEN_BOARD_PRS:
            break
    return created


def op_sync_staging(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Merge ``main`` into ``staging`` so promote has a current integration branch."""
    del args
    preview = staging_preview()
    table = getattr(ctx, "table", None)
    if preview.get("error"):
        if table is not None:
            cache_staging_preview(table, preview)
        return {"error": preview["error"], "preview": preview}
    if int(preview.get("behindBy") or 0) <= 0:
        if table is not None:
            cache_staging_preview(table, preview)
        return {"ok": True, "alreadyCurrent": True, "preview": preview}
    repo = _repo()
    try:
        merged = _gh(
            "POST",
            f"/repos/{repo}/merges",
            {
                "base": "staging",
                "head": "main",
                "commit_message": "board: sync staging with main",
            },
        )
    except board_github.GitHubSnapshotError as exc:
        return {"error": str(exc)[:200], "preview": preview}
    after = staging_preview()
    if table is not None:
        cache_staging_preview(table, after)
    sha = ""
    if isinstance(merged, dict):
        sha = str(merged.get("sha") or "")[:12]
    return {"ok": True, "mergedSha": sha, "before": preview, "preview": after}


def _pick_engineer(table: Any, engineers: list[str]) -> str:
    counts: dict[str, int] = {sid: 0 for sid in engineers}
    for status in ("queued", "running", "waiting_approval", "review"):
        for task in board_store.list_tasks(table, status, limit=80):
            assignee = str(task.get("assignee") or "")
            if assignee in counts:
                counts[assignee] += 1
    return min(engineers, key=lambda sid: (counts[sid], sid))


def on_review_delivered(table: Any, settings: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    ref = task.get("eventRef") or {}
    try:
        pr_number = int(ref.get("prNumber") or str(ref.get("id") or "").split(":")[-1] or 0)
    except (TypeError, ValueError):
        return {}
    if pr_number <= 0:
        return {}
    text = board_staff.read_deliverable(task, limit=20_000)
    parsed = parse_review_verdict(text)
    if not parsed:
        return {"skipped": "no verdict"}
    source_task = str(ref.get("taskId") or "")
    run = _get_run(table, source_task) if source_task else {}
    issue = int(run.get("issue") or 0)
    review_rounds = int(run.get("reviewRounds") or 0)
    roster = board_staff.seats_by_id(table, settings)
    engineer = str(task.get("eventRef", {}).get("engineer") or "")
    if not engineer:
        engineer = _pick_engineer(
            table, [sid for sid in ("engineer-1", "engineer-2") if (roster.get(sid) or {}).get("isActive")] or ["engineer-1"]
        )
    try:
        bundle = review_bundle(pr_number)
        ref["headSha"] = bundle.get("sha")
        task["eventRef"] = ref
        board_store.put_task(table, task)
    except (CodeError, board_github.GitHubSnapshotError) as exc:
        _log_event("warning", tag="board_code_head_sha_failed", error=str(exc)[:200])
    if parsed["verdict"] == "changes":
        # Independent of how many times the first engineer dispatched the runner.
        if review_rounds >= BOARD_CODE_REVIEW_MAX_ROUNDS - 1:
            return {"verdict": "changes", "stopped": "max rounds"}
        notes_list = [str(n) for n in (parsed.get("notes") or []) if n]
        if _notes_are_pending_only(notes_list):
            return {"verdict": "changes", "skipped": "ci pending"}
        notes = " ".join(notes_list) or "Address the architect review notes."
        if issue <= 0:
            return {"verdict": "changes", "skipped": "no issue"}
        failure = str(run.get("failureExcerpt") or run.get("failureLine") or "").strip()
        next_round = review_rounds + 2
        reopened = str(run.get("ownerReopenedAt") or "").strip()
        reopen_note = f" Owner reopened this revision at {reopened}." if reopened else ""
        excerpt_note = f"\nCI failure:\n{failure[:1200]}" if failure else ""
        brief = (
            f"Revise PR #{pr_number} (round {next_round}). Architect notes: {notes}."
            f"{reopen_note}{excerpt_note} "
            "Call code_run_task ONCE with a brief that fixes exactly these points, then call task_finish. "
            "Do not poll CI; the board polls it for you."
        )
        try:
            follow = board_staff.create_task(
                table,
                settings,
                assignee=engineer,
                origin="event",
                brief=brief[:4000],
                deliverable_type="pr",
                sla_hours=24,
                event_ref={"kind": "code-implement", "id": f"issue:{issue}:r{next_round}", "issueNumber": issue, "prNumber": pr_number},
                created_by="board_code",
            )
        except board_staff.StaffError as exc:
            return {"verdict": "changes", "error": str(exc)[:200]}
        if source_task:
            run["reviewRounds"] = review_rounds + 1
            _put_run(table, source_task, run)
        return {"verdict": "changes", "taskId": follow.get("taskId")}
    try:
        follow = board_staff.create_task(
            table,
            settings,
            assignee=engineer,
            origin="event",
            brief=f"Architect accepted PR #{pr_number}. Call code_merge_staging with prNumber={pr_number}.",
            deliverable_type="pr",
            sla_hours=12,
            event_ref={"kind": "code-merge", "id": f"pr:{pr_number}", "prNumber": pr_number},
            created_by="board_code",
        )
    except board_staff.StaffError as exc:
        return {"verdict": "accept", "error": str(exc)[:200]}
    return {"verdict": "accept", "taskId": follow.get("taskId")}


_STALE_BRANCH_PREFIX = "board/"
_STALE_BRANCH_SWEEP_CAP = 20
_STALE_BRANCH_SWEEP_CACHE = "code:branch-sweep"
_STALE_BRANCH_SWEEP_INTERVAL = timedelta(hours=6)
# A runner pushes ``board/{taskId}`` and opens the PR in the same job step;
# never delete a head whose run is still that fresh.
_STALE_BRANCH_MIN_RUN_AGE = timedelta(hours=2)
_STALE_BRANCH_KEEP = frozenset({"board/dry-run"})
_STALE_BRANCH_PAGE_SIZE = 100
_STALE_BRANCH_MAX_PAGES = 10


def _list_repo_branches(repo: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, _STALE_BRANCH_MAX_PAGES + 1):
        raw = (
            _gh(
                "GET",
                f"/repos/{repo}/branches?per_page={_STALE_BRANCH_PAGE_SIZE}&page={page}",
            )
            or []
        )
        if not isinstance(raw, list):
            break
        out.extend(row for row in raw if isinstance(row, dict))
        if len(raw) < _STALE_BRANCH_PAGE_SIZE:
            break
    return out


def _branch_run_is_fresh(table: Any, name: str) -> bool:
    task_id = name[len(_STALE_BRANCH_PREFIX) :]
    row = _get_run(table, task_id) if task_id else {}
    if not row or row.get("prNumber"):
        return False
    started = _parse_iso(str(row.get("dispatchedAt") or ""))
    return started is None or datetime.now(timezone.utc) - started < _STALE_BRANCH_MIN_RUN_AGE


def sweep_stale_board_branches(table: Any, *, force: bool = False) -> list[str]:
    """Delete ``board/*`` heads that have no open pull request.

    Covers merged PRs, closed-unmerged PRs, and runner branches that never
    opened a PR. Leaves ``board/dry-run``, any branch with an open PR,
    and any head whose runner dispatch is under two hours old. Runs at most
    every six hours unless ``force``. A 403 here means the board GitHub
    token needs Contents: write.
    """
    if not force:
        hit = board_store.get_cache(table, _STALE_BRANCH_SWEEP_CACHE)
        payload = hit.get("payload") if isinstance(hit, dict) else None
        last = _parse_iso(str((payload or {}).get("ranAt") or "")) if isinstance(payload, dict) else None
        if last is not None and datetime.now(timezone.utc) - last < _STALE_BRANCH_SWEEP_INTERVAL:
            return []
    board_store.put_cache(
        table,
        _STALE_BRANCH_SWEEP_CACHE,
        {"ranAt": board_store.now_iso()},
        ttl_seconds=int(_STALE_BRANCH_SWEEP_INTERVAL.total_seconds()) * 2,
    )
    repo = _repo()
    owner = repo.split("/", 1)[0]
    deleted: list[str] = []
    try:
        raw = _list_repo_branches(repo)
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_branch_sweep_list_failed", error=str(exc)[:200])
        return []
    for row in raw:
        name = str(row.get("name") or "")
        if not name.startswith(_STALE_BRANCH_PREFIX) or name in _STALE_BRANCH_KEEP:
            continue
        if _branch_run_is_fresh(table, name):
            continue
        try:
            pulls = (
                _gh("GET", f"/repos/{repo}/pulls?head={owner}:{name}&state=open&per_page=5") or []
            )
        except board_github.GitHubSnapshotError as exc:
            _log_event(
                "warning",
                tag="board_code_branch_sweep_pr_failed",
                branch=name,
                error=str(exc)[:200],
            )
            continue
        if isinstance(pulls, list) and any(isinstance(pr, dict) for pr in pulls):
            continue
        try:
            _gh("DELETE", f"/repos/{repo}/git/refs/heads/{name}")
        except board_github.GitHubSnapshotError as exc:
            _log_event(
                "warning",
                tag="board_code_branch_sweep_delete_failed",
                branch=name,
                error=str(exc)[:200],
            )
            continue
        deleted.append(name)
        if len(deleted) >= _STALE_BRANCH_SWEEP_CAP:
            break
    if deleted:
        _log_event("info", tag="board_code_branch_sweep", deleted=",".join(deleted)[:400])
    return deleted


def handle_tick(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    reviews = poll_runs(table, settings)
    stale = sweep_stale_board_branches(table)
    assigned = maybe_assign_ready_issues(table, settings)
    preview = cache_staging_preview(table)
    sync = maybe_daily_staging_sync(table, settings, preview=preview)
    return {
        "ok": True,
        "reviews": len(reviews),
        "assigned": len(assigned),
        "stagingSync": bool(sync),
        "staleBranches": len(stale),
    }
