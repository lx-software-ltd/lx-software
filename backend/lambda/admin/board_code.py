"""Engineering runner: dispatch Cursor-on-Actions, review PRs, merge staging.

See docs/architecture/executive-board-autonomy-implementation.md WP10.
Workflows live in the siutindei repo (appendix A). This module only dispatches
and enforces policy.
"""

from __future__ import annotations

import json
import re
from typing import Any

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
MAX_REVIEW_ROUNDS = 2
KINDS = frozenset({"feature", "fix", "content"})
CI_OK = frozenset({"success", "neutral", "skipped"})
_ISSUE_RE = re.compile(r"#(\d+)")
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
_RUN_INDEX = "code:runs"


class CodeError(ValueError):
    """Runner policy or GitHub dispatch failure."""


def _repo() -> str:
    return board_github.repo_full_name()


def _gh(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    return board_github._request(method, path, body=body)  # noqa: SLF001


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


def changed_lines(files: list[dict[str, Any]]) -> int:
    total = 0
    for row in files:
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


def dispatch_workflow(name: str, inputs: dict[str, Any], *, ref: str = "staging") -> dict[str, Any]:
    repo = _repo()
    _gh(
        "POST",
        f"/repos/{repo}/actions/workflows/{name}/dispatches",
        {"ref": ref, "inputs": {str(k): str(v) for k, v in inputs.items()}},
    )
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


def issue_has_open_board_pr(issue_number: int, table: Any | None = None) -> bool:
    for pr in list_open_board_prs():
        if _issue_from_pr(pr) == issue_number:
            return True
    if table is not None:
        for task_id in _run_index(table):
            row = _get_run(table, task_id)
            if int(row.get("issue") or 0) == issue_number and not row.get("prNumber"):
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


def ci_success(sha: str) -> bool:
    if not sha:
        return False
    repo = _repo()
    checks = _gh("GET", f"/repos/{repo}/commits/{sha}/check-runs") or {}
    runs = checks.get("check_runs") if isinstance(checks, dict) else None
    if isinstance(runs, list) and runs:
        return all(
            str(r.get("status") or "") == "completed" and str(r.get("conclusion") or "") in CI_OK
            for r in runs
            if isinstance(r, dict)
        )
    status = _gh("GET", f"/repos/{repo}/commits/{sha}/status") or {}
    return isinstance(status, dict) and str(status.get("state") or "") == "success"


def _pr_files(number: int) -> list[dict[str, Any]]:
    repo = _repo()
    raw = _gh("GET", f"/repos/{repo}/pulls/{int(number)}/files?per_page=100") or []
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


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
    return {
        "prNumber": int(pr_number),
        "title": pr.get("title"),
        "base": (pr.get("base") or {}).get("ref"),
        "head": (pr.get("head") or {}).get("ref"),
        "draft": bool(pr.get("draft")),
        "changedLines": changed_lines(files),
        "changedPaths": [str(f.get("filename") or "") for f in files],
        "protectedPaths": files_protected(files),
        "ci": "success" if ci_success(sha) else "pending_or_failed",
        "sha": sha,
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


def _find_task(table: Any, kind: str, event_id: str, *, statuses: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    wanted = statuses or ("queued", "running", "review", "returned", "delivered", "needs_owner")
    for status in wanted:
        for task in board_store.list_tasks(table, status, limit=200):
            ref = task.get("eventRef") or {}
            if ref.get("kind") == kind and str(ref.get("id") or "") == event_id:
                return task
    return None


def architect_accepted(table: Any, pr_number: int) -> bool:
    task = _find_task(table, "code-review", f"pr:{int(pr_number)}", statuses=("delivered",))
    if not task:
        return False
    text = board_staff.read_deliverable(task, limit=20_000)
    parsed = parse_review_verdict(text)
    return parsed.get("verdict") == "accept"


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


def op_run_task(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        issue = int(args.get("issueNumber") or 0)
    except (TypeError, ValueError):
        raise CodeError("issueNumber is required") from None
    if issue <= 0:
        raise CodeError("issueNumber is required")
    kind = str(args.get("kind") or "feature").strip().lower()
    if kind not in KINDS:
        raise CodeError("kind must be feature, fix or content")
    brief = str(args.get("brief") or "").strip()
    if not brief:
        raise CodeError("brief is required")
    if issue_has_open_board_pr(issue, ctx.table):
        raise CodeError(f"an open board/* pull request already references #{issue}")
    task_id = str(ctx.task_id or args.get("taskId") or board_store.new_id())
    dispatched = dispatch_workflow(
        WORKFLOW_AGENT,
        {"task_id": task_id, "issue": str(issue), "brief": brief[:4000], "kind": kind},
        ref="staging",
    )
    payload = {
        "taskId": task_id,
        "issue": issue,
        "kind": kind,
        "brief": brief[:4000],
        "rounds": int((_get_run(ctx.table, task_id).get("rounds") or 0)) + 1,
        "dispatchedAt": board_store.now_iso(),
        "workflow": WORKFLOW_AGENT,
    }
    _put_run(ctx.table, task_id, payload)
    return {**dispatched, **payload}


def op_get_run(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    task_id = str(args.get("taskId") or ctx.task_id or "").strip()
    if not task_id:
        raise CodeError("taskId is required")
    stored = _get_run(ctx.table, task_id)
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
    if out.get("prNumber"):
        stored["prNumber"] = out["prNumber"]
        stored["runStatus"] = out["runStatus"]
        stored["conclusion"] = out["conclusion"]
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


def op_merge_staging(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    try:
        number = int(args.get("prNumber") or 0)
    except (TypeError, ValueError):
        raise CodeError("prNumber is required") from None
    if number <= 0:
        raise CodeError("prNumber is required")
    return dispatch_workflow(WORKFLOW_MERGE, {"pr_number": str(number)}, ref="staging")


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


def _ensure_rebase_task(table: Any, settings: dict[str, Any]) -> dict[str, Any] | None:
    if _find_task(table, "ops", "rebase-staging"):
        return None
    roster = board_staff.seats_by_id(table, settings)
    assignee = "architect" if (roster.get("architect") or {}).get("isActive") else "cto"
    try:
        return board_staff.create_task(
            table,
            settings,
            assignee=assignee,
            origin="event",
            brief="staging is behind main. Rebase staging onto main before promoting. Manual in v1.",
            deliverable_type="markdown",
            sla_hours=24,
            event_ref={"kind": "ops", "id": "rebase-staging"},
            created_by="board_code",
            status="needs_owner",
        )
    except board_staff.StaffError as exc:
        _log_event("info", tag="board_code_rebase_skipped", error=str(exc)[:200])
        return None


def op_promote(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or "production").strip() or "production"
    preview = compare_staging()
    if int(preview.get("behindBy") or 0) > 0:
        _ensure_rebase_task(ctx.table, ctx.settings)
        return {"error": "staging is behind main; rebase first", "preview": preview}
    dispatched = dispatch_workflow(WORKFLOW_PROMOTE, {"kind": kind}, ref="main")
    return {**dispatched, "preview": preview}


def staging_preview() -> dict[str, Any]:
    try:
        return compare_staging()
    except board_github.GitHubSnapshotError as exc:
        return {"error": str(exc)[:200], "commits": [], "canPromote": False, "behindBy": 0, "aheadBy": 0}


def queue_promote_approval(table: Any, settings: dict[str, Any], user_sub: str) -> dict[str, Any]:
    import board_tools

    preview = staging_preview()
    if preview.get("error"):
        raise CodeError(str(preview["error"]))
    if int(preview.get("behindBy") or 0) > 0:
        _ensure_rebase_task(table, settings)
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


def poll_runs(table: Any, settings: dict[str, Any]) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    if not board_staff.enabled(settings):
        return created
    roster = board_staff.seats_by_id(table, settings)
    architect = "architect" if (roster.get("architect") or {}).get("isActive") else "cto"
    for task_id in _run_index(table):
        try:
            state = op_get_run(type("C", (), {"table": table, "task_id": task_id, "settings": settings})(), {"taskId": task_id})
        except (CodeError, board_github.GitHubSnapshotError) as exc:
            _log_event("warning", tag="board_code_poll_failed", taskId=task_id, error=str(exc)[:200])
            continue
        pr_number = state.get("prNumber")
        if not pr_number:
            continue
        event_id = f"pr:{int(pr_number)}"
        if _find_task(table, "code-review", event_id):
            continue
        try:
            task = board_staff.create_task(
                table,
                settings,
                assignee=architect,
                origin="event",
                brief=(
                    f"Review PR #{pr_number} ({state.get('runName') or task_id}). "
                    "Call code_review_pr and deliver Markdown that ends with "
                    '```json {"verdict":"accept"|"changes","notes":[…]}```'
                ),
                deliverable_type="markdown",
                sla_hours=24,
                event_ref={"kind": "code-review", "id": event_id, "prNumber": int(pr_number), "taskId": task_id},
                created_by="board_code",
            )
            created.append(task)
        except board_staff.StaffError as exc:
            _log_event("info", tag="board_code_review_skipped", error=str(exc)[:200])
    return created


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
    repo = _repo()
    try:
        raw = _gh("GET", f"/repos/{repo}/issues?state=open&labels=board-ready&sort=created&direction=asc&per_page=20") or []
    except board_github.GitHubSnapshotError as exc:
        _log_event("warning", tag="board_code_list_issues_failed", error=str(exc)[:200])
        return []
    issues = [i for i in raw if isinstance(i, dict) and not i.get("pull_request")] if isinstance(raw, list) else []
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
        except board_staff.StaffError as exc:
            _log_event("info", tag="board_code_assign_skipped", error=str(exc)[:200])
            continue
        if len(open_prs) + len(created) >= MAX_OPEN_BOARD_PRS:
            break
    return created


def _pick_engineer(table: Any, engineers: list[str]) -> str:
    counts: dict[str, int] = {sid: 0 for sid in engineers}
    for status in ("queued", "running", "review"):
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
    kind = str(run.get("kind") or "feature")
    rounds = int(run.get("rounds") or 1)
    roster = board_staff.seats_by_id(table, settings)
    engineer = str(task.get("eventRef", {}).get("engineer") or "")
    if not engineer:
        engineer = _pick_engineer(
            table, [sid for sid in ("engineer-1", "engineer-2") if (roster.get(sid) or {}).get("isActive")] or ["engineer-1"]
        )
    if parsed["verdict"] == "changes":
        if rounds >= MAX_REVIEW_ROUNDS:
            return {"verdict": "changes", "stopped": "max rounds"}
        notes = " ".join(parsed.get("notes") or []) or "Address the architect review notes."
        if issue <= 0:
            return {"verdict": "changes", "skipped": "no issue"}
        try:
            follow = board_staff.create_task(
                table,
                settings,
                assignee=engineer,
                origin="event",
                brief=f"Revise PR #{pr_number} (round {rounds + 1}). {notes} Call code_run_task again.",
                deliverable_type="pr",
                sla_hours=24,
                event_ref={"kind": "code-implement", "id": f"issue:{issue}:r{rounds + 1}", "issueNumber": issue, "prNumber": pr_number},
                created_by="board_code",
            )
        except board_staff.StaffError as exc:
            return {"verdict": "changes", "error": str(exc)[:200]}
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


def handle_tick(table: Any, settings: dict[str, Any]) -> dict[str, Any]:
    if not board_staff.enabled(settings):
        return {"ok": True, "skipped": "disabled"}
    reviews = poll_runs(table, settings)
    assigned = maybe_assign_ready_issues(table, settings)
    return {"ok": True, "reviews": len(reviews), "assigned": len(assigned)}
