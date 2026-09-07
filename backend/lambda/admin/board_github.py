"""Executive Board: access to the Siu Tin Dei GitHub repository.

Two uses share this module:

- the cached **snapshot** (README, AGENTS.md, architecture docs, open
  issues, recent commits, latest CI run) that feeds the context pack, and
- the on-demand **tool operations** board members call during chats and
  meetings (search issues, read a file, list CI runs, open an issue, ...).

The repository is public, so reads work without credentials (subject to
GitHub's anonymous rate limit). A fine-grained token in Secrets Manager
(``GITHUB_READ_TOKEN_SECRET_ARN``) raises the limit and is required for
writes (``issues: write``) and security alerts (``security_events: read``).
"""

from __future__ import annotations

import base64
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from admin_runtime import _get_secretsmanager_client
import board_deadline
from http_common import _log_event, _utc_iso_z
from openrouter_client import OpenRouterError, read_secret_string

DEFAULT_REPO = "lx-software-ltd/siutindei"
API_ORIGIN = "https://api.github.com"
HTTP_TIMEOUT_SECONDS = 25
MAX_DOC_CHARS = 6000
MAX_TOTAL_CHARS = 32000
MAX_DOC_FILES = 6
MAX_ISSUES = 30
MAX_COMMITS = 20
MAX_TOOL_FILE_CHARS = 12000
MAX_TOOL_LIST = 20
MAX_ISSUE_BODY_CHARS = 4000
MAX_COMMENT_CHARS = 1500
MAX_COMMENTS = 10
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._\-/ ]+$")
# ``repo:``, ``org:`` and ``user:`` qualifiers would let a search escape the
# board's repository; they are stripped (quoted or bare values) before the
# repo qualifier is applied.
_SCOPE_QUALIFIER_RE = re.compile(r"(?<!\S)-?(?:repo|org|user):(?:\"[^\"]*\"|\S+)", re.IGNORECASE)

_token_cache: str | None = None
_token_checked = False


class GitHubSnapshotError(RuntimeError):
    """User-facing failure while talking to GitHub."""

    def __init__(self, message: str, *, status: int | None = None, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _header(headers: Any, name: str) -> str | None:
    """Case-insensitive header lookup over ``HTTPMessage`` or a plain dict."""
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if callable(getter):
        value = getter(name)
        if value is None and isinstance(headers, dict):
            lowered = name.lower()
            value = next((v for k, v in headers.items() if str(k).lower() == lowered), None)
        return str(value) if value is not None else None
    return None


def _rate_limit_wait_seconds(exc: urlerror.HTTPError) -> int | None:
    """Seconds to wait when GitHub signalled a rate limit, else ``None``."""
    if exc.code not in (403, 429):
        return None
    headers = getattr(exc, "headers", None)
    retry_after = _header(headers, "Retry-After")
    if retry_after:
        try:
            return max(1, int(float(retry_after)))
        except ValueError:
            return 60
    remaining = _header(headers, "X-RateLimit-Remaining")
    if remaining is not None and remaining.strip() == "0":
        reset = _header(headers, "X-RateLimit-Reset")
        try:
            reset_at = int(float(reset)) if reset else 0
        except ValueError:
            reset_at = 0
        now = int(datetime.now(timezone.utc).timestamp())
        return max(1, reset_at - now) if reset_at else 60
    return None


GitHubApiError = GitHubSnapshotError


def repo_full_name() -> str:
    return (os.environ.get("BOARD_GITHUB_REPO") or "").strip() or DEFAULT_REPO


def snapshot_enabled() -> bool:
    """Reads never need credentials: the repository is public."""
    return bool(repo_full_name())


def token_configured() -> bool:
    return bool(
        (os.environ.get("GITHUB_READ_TOKEN") or "").strip()
        or (os.environ.get("GITHUB_READ_TOKEN_SECRET_ARN") or "").strip()
    )


def write_enabled() -> bool:
    return token_configured()


def _token() -> str:
    """Bearer token, or ``""`` when none is configured (anonymous reads)."""
    global _token_cache, _token_checked
    if _token_checked and _token_cache is not None:
        return _token_cache
    direct = (os.environ.get("GITHUB_READ_TOKEN") or "").strip()
    if direct:
        _token_cache, _token_checked = direct, True
        return direct
    arn = (os.environ.get("GITHUB_READ_TOKEN_SECRET_ARN") or "").strip()
    if not arn:
        _token_cache, _token_checked = "", True
        return ""
    try:
        _token_cache = read_secret_string(
            _get_secretsmanager_client(), arn, what="GitHub token"
        )
    except OpenRouterError as exc:
        raise GitHubSnapshotError(str(exc)) from exc
    _token_checked = True
    return _token_cache


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    accept: str = "application/vnd.github+json",
    timeout: int = HTTP_TIMEOUT_SECONDS,
) -> Any:
    url = path if path.startswith("http") else f"{API_ORIGIN}{path}"
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lxsoftware-admin-board",
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, method=method, headers=headers)  # noqa: S310 - fixed API origin
    try:
        with urlrequest.urlopen(req, timeout=board_deadline.remaining(timeout)) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", errors="replace")
    except urlerror.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        wait = _rate_limit_wait_seconds(exc)
        if wait is not None:
            _log_event("warning", tag="board_github_rate_limited", status=exc.code, retryAfter=wait, path=path[:120])
            raise GitHubSnapshotError(
                f"GitHub rate limit; retry after {wait}s", status=exc.code, retry_after=wait
            ) from exc
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str(payload.get("message") or "") if isinstance(payload, dict) else ""
        except Exception:  # pragma: no cover - defensive
            detail = ""
        suffix = f": {detail[:200]}" if detail else ""
        if exc.code in (401, 403) and not token:
            suffix += " (no GitHub token configured; anonymous access is rate-limited and cannot write)"
        raise GitHubSnapshotError(
            f"GitHub API returned status {exc.code} for {method} {path}{suffix}", status=exc.code
        ) from exc
    except urlerror.URLError as exc:
        raise GitHubSnapshotError(f"GitHub API transport error: {exc.reason}") from exc
    if accept.endswith("raw"):
        return text
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GitHubSnapshotError("GitHub API returned invalid JSON") from exc


def _get(path: str, *, accept: str = "application/vnd.github+json") -> Any:
    return _request("GET", path, accept=accept)


def _file_text(repo: str, path: str) -> str | None:
    data = _get(f"/repos/{repo}/contents/{urlparse.quote(path)}")
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if not isinstance(content, str):
        return None
    try:
        text = base64.b64decode(content).decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - defensive
        return None
    return _cap(text, MAX_DOC_CHARS)


def _cap(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 15].rstrip() + "\n[... truncated]"


def fetch_snapshot() -> dict[str, Any]:
    repo = repo_full_name()
    meta = _get(f"/repos/{repo}")
    if not isinstance(meta, dict):
        raise GitHubSnapshotError(f"Repository {repo} not found or token lacks access")
    default_branch = str(meta.get("default_branch") or "main")

    docs: list[dict[str, str]] = []
    for path in ("README.md", "AGENTS.md"):
        text = _file_text(repo, path)
        if text:
            docs.append({"path": path, "text": text})
    listing = _get(f"/repos/{repo}/contents/docs/architecture")
    if isinstance(listing, list):
        md_files = [
            str(e.get("path"))
            for e in listing
            if isinstance(e, dict)
            and e.get("type") == "file"
            and str(e.get("name") or "").lower().endswith(".md")
        ]
        for path in sorted(md_files)[:MAX_DOC_FILES]:
            text = _file_text(repo, path)
            if text:
                docs.append({"path": path, "text": text})

    issues_raw = _get(f"/repos/{repo}/issues?state=open&per_page={MAX_ISSUES}&sort=updated")
    issues: list[dict[str, Any]] = []
    if isinstance(issues_raw, list):
        for it in issues_raw:
            if not isinstance(it, dict) or it.get("pull_request"):
                continue
            issues.append(
                {
                    "number": it.get("number"),
                    "title": _cap(str(it.get("title") or ""), 200),
                    "labels": [
                        str(lb.get("name"))
                        for lb in (it.get("labels") or [])
                        if isinstance(lb, dict) and lb.get("name")
                    ],
                    "updatedAt": it.get("updated_at"),
                }
            )

    commits_raw = _get(f"/repos/{repo}/commits?sha={urlparse.quote(default_branch)}&per_page={MAX_COMMITS}")
    commits: list[dict[str, Any]] = []
    if isinstance(commits_raw, list):
        for c in commits_raw:
            if not isinstance(c, dict):
                continue
            commit = c.get("commit") or {}
            message = str(commit.get("message") or "").splitlines()[0] if commit else ""
            author = (commit.get("author") or {}) if isinstance(commit, dict) else {}
            commits.append(
                {
                    "sha": str(c.get("sha") or "")[:8],
                    "message": _cap(message, 160),
                    "date": author.get("date"),
                }
            )

    runs_raw = _get(
        f"/repos/{repo}/actions/runs?branch={urlparse.quote(default_branch)}&per_page=5"
    )
    ci: list[dict[str, Any]] = []
    if isinstance(runs_raw, dict):
        for run in runs_raw.get("workflow_runs") or []:
            if not isinstance(run, dict):
                continue
            ci.append(
                {
                    "name": _cap(str(run.get("name") or ""), 80),
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "updatedAt": run.get("updated_at"),
                }
            )

    snapshot = {
        "repo": repo,
        "defaultBranch": default_branch,
        "description": _cap(str(meta.get("description") or ""), 400),
        "openIssuesCount": int(meta.get("open_issues_count") or 0),
        "pushedAt": meta.get("pushed_at"),
        "docs": docs,
        "issues": issues,
        "commits": commits,
        "ci": ci,
        "fetchedAt": _utc_iso_z(datetime.now(timezone.utc)),
    }
    snapshot["text"] = render_snapshot(snapshot)
    _log_event(
        "info",
        tag="board_repo_snapshot",
        repo=repo,
        docs=len(docs),
        issues=len(issues),
        commits=len(commits),
        chars=len(snapshot["text"]),
    )
    return snapshot


def render_snapshot(snapshot: dict[str, Any]) -> str:
    parts: list[str] = [
        f"Repository {snapshot.get('repo')} (default branch {snapshot.get('defaultBranch')}, "
        f"last push {snapshot.get('pushedAt') or 'unknown'}, "
        f"{snapshot.get('openIssuesCount', 0)} open issues)."
    ]
    if snapshot.get("description"):
        parts.append(f"Description: {snapshot['description']}")
    ci = snapshot.get("ci") or []
    if ci:
        parts.append("Latest CI runs:")
        for run in ci[:5]:
            parts.append(
                f"- {run.get('name')}: {run.get('status')} / {run.get('conclusion') or 'n/a'} "
                f"({run.get('updatedAt')})"
            )
    commits = snapshot.get("commits") or []
    if commits:
        parts.append("Recent commits:")
        for c in commits:
            parts.append(f"- {c.get('sha')} {c.get('message')} ({str(c.get('date') or '')[:10]})")
    issues = snapshot.get("issues") or []
    if issues:
        parts.append("Open issues:")
        for it in issues:
            labels = f" [{', '.join(it.get('labels') or [])}]" if it.get("labels") else ""
            parts.append(f"- #{it.get('number')} {it.get('title')}{labels}")
    for doc in snapshot.get("docs") or []:
        parts.append("")
        parts.append(f"===== {doc.get('path')} =====")
        parts.append(str(doc.get("text") or ""))
    text = "\n".join(parts)
    return _cap(text, MAX_TOTAL_CHARS)


def snapshot_age_seconds(snapshot: dict[str, Any] | None) -> float | None:
    if not snapshot:
        return None
    raw = snapshot.get("fetchedAt")
    if not isinstance(raw, str):
        return None
    try:
        text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        fetched = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - fetched.astimezone(timezone.utc)).total_seconds()


def public_snapshot_meta(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Snapshot metadata for the SPA (omits the large rendered text)."""
    if not snapshot:
        return None
    return {
        "repo": snapshot.get("repo"),
        "fetchedAt": snapshot.get("fetchedAt"),
        "openIssuesCount": snapshot.get("openIssuesCount", 0),
        "docs": [d.get("path") for d in snapshot.get("docs") or []],
        "commits": len(snapshot.get("commits") or []),
        "ci": (snapshot.get("ci") or [None])[0],
        "chars": len(str(snapshot.get("text") or "")),
    }


def reset_token_cache_for_tests() -> None:
    global _token_cache, _token_checked
    _token_cache = None
    _token_checked = False


# ---------------------------------------------------------------------------
# Tool operations (called by board_tools through the registry)
# ---------------------------------------------------------------------------

def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(low, out), high)


def _issue_number(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise GitHubSnapshotError("number must be an integer issue or pull request number") from None
    if number <= 0:
        raise GitHubSnapshotError("number must be positive")
    return number


def _issue_summary(it: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": it.get("number"),
        "title": _cap(str(it.get("title") or ""), 200),
        "state": it.get("state"),
        "isPullRequest": bool(it.get("pull_request")),
        "labels": [
            str(lb.get("name")) for lb in (it.get("labels") or []) if isinstance(lb, dict) and lb.get("name")
        ],
        "author": ((it.get("user") or {}).get("login") if isinstance(it.get("user"), dict) else None),
        "comments": it.get("comments"),
        "createdAt": it.get("created_at"),
        "updatedAt": it.get("updated_at"),
        "url": it.get("html_url"),
    }


def strip_scope_qualifiers(query: str) -> tuple[str, list[str]]:
    """Remove ``repo:``/``org:``/``user:`` qualifiers; return (query, removed)."""
    removed = [m.group(0) for m in _SCOPE_QUALIFIER_RE.finditer(query)]
    cleaned = " ".join(_SCOPE_QUALIFIER_RE.sub(" ", query).split())
    return cleaned, removed


def op_search_issues(args: dict[str, Any]) -> dict[str, Any]:
    repo = repo_full_name()
    query = " ".join(str(args.get("query") or "").split())[:200]
    query, stripped = strip_scope_qualifiers(query)
    if stripped:
        _log_event("info", tag="board_github_search_qualifiers_stripped", stripped=stripped[:5])
    state = str(args.get("state") or "open").lower()
    if state not in ("open", "closed", "all"):
        state = "open"
    kind = str(args.get("type") or "issue").lower()
    if kind not in ("issue", "pr", "any"):
        kind = "issue"
    limit = _clamp_int(args.get("limit"), default=10, low=1, high=MAX_TOOL_LIST)
    q_parts = [f"repo:{repo}"]
    if state != "all":
        q_parts.append(f"state:{state}")
    if kind != "any":
        q_parts.append(f"type:{kind}")
    if query:
        q_parts.append(query)
    data = _get(f"/search/issues?q={urlparse.quote(' '.join(q_parts))}&per_page={limit}&sort=updated")
    items = data.get("items") if isinstance(data, dict) else None
    results = [_issue_summary(it) for it in (items or []) if isinstance(it, dict)]
    out: dict[str, Any] = {
        "repo": repo,
        "query": " ".join(q_parts),
        "totalCount": int(data.get("total_count") or 0) if isinstance(data, dict) else 0,
        "items": results,
    }
    if stripped:
        out["strippedQualifiers"] = stripped
        out["note"] = f"Search is limited to {repo}; repo:/org:/user: qualifiers were ignored."
    return out


def op_list_releases(args: dict[str, Any]) -> dict[str, Any]:
    """GitHub releases (REST). Discussions need GraphQL and are not exposed."""
    repo = repo_full_name()
    limit = _clamp_int(args.get("limit"), default=10, low=1, high=MAX_TOOL_LIST)
    raw = _get(f"/repos/{repo}/releases?per_page={limit}")
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for rel in raw:
            if not isinstance(rel, dict):
                continue
            items.append(
                {
                    "id": rel.get("id"),
                    "tag": rel.get("tag_name"),
                    "name": _cap(str(rel.get("name") or rel.get("tag_name") or ""), 120),
                    "draft": bool(rel.get("draft")),
                    "prerelease": bool(rel.get("prerelease")),
                    "author": ((rel.get("author") or {}).get("login") if isinstance(rel.get("author"), dict) else None),
                    "createdAt": rel.get("created_at"),
                    "publishedAt": rel.get("published_at"),
                    "notes": _cap(str(rel.get("body") or ""), MAX_COMMENT_CHARS),
                    "url": rel.get("html_url"),
                }
            )
    return {"repo": repo, "items": items}


def op_get_issue(args: dict[str, Any]) -> dict[str, Any]:
    repo = repo_full_name()
    number = _issue_number(args.get("number"))
    it = _get(f"/repos/{repo}/issues/{number}")
    if not isinstance(it, dict):
        return {"error": f"Issue #{number} not found in {repo}"}
    out = _issue_summary(it)
    out["body"] = _cap(str(it.get("body") or ""), MAX_ISSUE_BODY_CHARS)
    out["assignees"] = [
        str(a.get("login")) for a in (it.get("assignees") or []) if isinstance(a, dict) and a.get("login")
    ]
    comments_raw = _get(f"/repos/{repo}/issues/{number}/comments?per_page={MAX_COMMENTS}")
    comments: list[dict[str, Any]] = []
    if isinstance(comments_raw, list):
        for c in comments_raw:
            if not isinstance(c, dict):
                continue
            comments.append(
                {
                    "author": ((c.get("user") or {}).get("login") if isinstance(c.get("user"), dict) else None),
                    "createdAt": c.get("created_at"),
                    "body": _cap(str(c.get("body") or ""), MAX_COMMENT_CHARS),
                }
            )
    out["recentComments"] = comments
    return out


def op_list_pull_requests(args: dict[str, Any]) -> dict[str, Any]:
    repo = repo_full_name()
    state = str(args.get("state") or "open").lower()
    if state not in ("open", "closed", "all"):
        state = "open"
    limit = _clamp_int(args.get("limit"), default=10, low=1, high=MAX_TOOL_LIST)
    raw = _get(f"/repos/{repo}/pulls?state={state}&per_page={limit}&sort=updated&direction=desc")
    items: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for pr in raw:
            if not isinstance(pr, dict):
                continue
            items.append(
                {
                    "number": pr.get("number"),
                    "title": _cap(str(pr.get("title") or ""), 200),
                    "state": pr.get("state"),
                    "draft": bool(pr.get("draft")),
                    "author": ((pr.get("user") or {}).get("login") if isinstance(pr.get("user"), dict) else None),
                    "head": ((pr.get("head") or {}).get("ref") if isinstance(pr.get("head"), dict) else None),
                    "createdAt": pr.get("created_at"),
                    "updatedAt": pr.get("updated_at"),
                    "mergedAt": pr.get("merged_at"),
                    "url": pr.get("html_url"),
                }
            )
    return {"repo": repo, "state": state, "items": items}


def op_list_workflow_runs(args: dict[str, Any]) -> dict[str, Any]:
    repo = repo_full_name()
    limit = _clamp_int(args.get("limit"), default=10, low=1, high=MAX_TOOL_LIST)
    branch = str(args.get("branch") or "").strip()
    query = f"per_page={limit}"
    if branch and _SAFE_PATH_RE.match(branch):
        query += f"&branch={urlparse.quote(branch)}"
    raw = _get(f"/repos/{repo}/actions/runs?{query}")
    runs: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for run in raw.get("workflow_runs") or []:
            if not isinstance(run, dict):
                continue
            head_commit = run.get("head_commit") if isinstance(run.get("head_commit"), dict) else {}
            commit_lines = str(head_commit.get("message") or "").splitlines()
            runs.append(
                {
                    "id": run.get("id"),
                    "name": _cap(str(run.get("name") or ""), 80),
                    "branch": run.get("head_branch"),
                    "event": run.get("event"),
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "commitMessage": _cap(commit_lines[0] if commit_lines else "", 120),
                    "updatedAt": run.get("updated_at"),
                    "url": run.get("html_url"),
                }
            )
    return {"repo": repo, "items": runs}


def op_list_commits(args: dict[str, Any]) -> dict[str, Any]:
    repo = repo_full_name()
    limit = _clamp_int(args.get("limit"), default=10, low=1, high=MAX_TOOL_LIST)
    query = f"per_page={limit}"
    path = str(args.get("path") or "").strip().strip("/")
    if path:
        if not _SAFE_PATH_RE.match(path) or ".." in path:
            raise GitHubSnapshotError("path contains unsupported characters")
        query += f"&path={urlparse.quote(path)}"
    raw = _get(f"/repos/{repo}/commits?{query}")
    commits: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for c in raw:
            if not isinstance(c, dict):
                continue
            commit = c.get("commit") or {}
            author = (commit.get("author") or {}) if isinstance(commit, dict) else {}
            commits.append(
                {
                    "sha": str(c.get("sha") or "")[:10],
                    "message": _cap(str(commit.get("message") or "").splitlines()[0] if commit else "", 160),
                    "author": author.get("name"),
                    "date": author.get("date"),
                    "url": c.get("html_url"),
                }
            )
    return {"repo": repo, "path": path or None, "items": commits}


def op_get_file(args: dict[str, Any]) -> dict[str, Any]:
    repo = repo_full_name()
    path = str(args.get("path") or "").strip().strip("/")
    if not path or not _SAFE_PATH_RE.match(path) or ".." in path:
        raise GitHubSnapshotError("path is required and may only contain letters, digits, '.', '_', '-', '/'")
    ref = str(args.get("ref") or "").strip()
    query = f"?ref={urlparse.quote(ref)}" if ref and _SAFE_PATH_RE.match(ref) else ""
    data = _get(f"/repos/{repo}/contents/{urlparse.quote(path)}{query}")
    if data is None:
        return {"error": f"{path} not found in {repo}"}
    if isinstance(data, list):
        return {
            "repo": repo,
            "path": path,
            "type": "dir",
            "entries": [
                {"name": e.get("name"), "type": e.get("type"), "size": e.get("size")}
                for e in data[:100]
                if isinstance(e, dict)
            ],
        }
    if not isinstance(data, dict):
        return {"error": "Unexpected response from GitHub"}
    content = data.get("content")
    text = ""
    if isinstance(content, str):
        try:
            text = base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            text = ""
    size = int(data.get("size") or 0)
    return {
        "repo": repo,
        "path": path,
        "type": "file",
        "size": size,
        "truncated": len(text) > MAX_TOOL_FILE_CHARS,
        "text": _cap(text, MAX_TOOL_FILE_CHARS),
        "url": data.get("html_url"),
    }


def op_list_security_alerts(args: dict[str, Any]) -> dict[str, Any]:
    repo = repo_full_name()
    limit = _clamp_int(args.get("limit"), default=20, low=1, high=50)
    out: dict[str, Any] = {"repo": repo, "dependabot": [], "codeScanning": [], "notes": []}
    try:
        dep = _get(f"/repos/{repo}/dependabot/alerts?state=open&per_page={limit}")
    except GitHubSnapshotError as exc:
        dep = None
        out["notes"].append(f"Dependabot alerts unavailable: {exc}")
    if isinstance(dep, list):
        for a in dep:
            if not isinstance(a, dict):
                continue
            adv = a.get("security_advisory") or {}
            dep_info = a.get("dependency") or {}
            pkg = dep_info.get("package") or {} if isinstance(dep_info, dict) else {}
            out["dependabot"].append(
                {
                    "number": a.get("number"),
                    "severity": (adv.get("severity") if isinstance(adv, dict) else None),
                    "package": (pkg.get("name") if isinstance(pkg, dict) else None),
                    "ecosystem": (pkg.get("ecosystem") if isinstance(pkg, dict) else None),
                    "summary": _cap(str(adv.get("summary") or "") if isinstance(adv, dict) else "", 200),
                    "manifest": (dep_info.get("manifest_path") if isinstance(dep_info, dict) else None),
                    "createdAt": a.get("created_at"),
                    "url": a.get("html_url"),
                }
            )
    elif dep is None and not out["notes"]:
        out["notes"].append("Dependabot alerts are not enabled or not visible for this repository.")
    try:
        cs = _get(f"/repos/{repo}/code-scanning/alerts?state=open&per_page={limit}")
    except GitHubSnapshotError as exc:
        cs = None
        out["notes"].append(f"Code scanning alerts unavailable: {exc}")
    if isinstance(cs, list):
        for a in cs:
            if not isinstance(a, dict):
                continue
            rule = a.get("rule") or {}
            loc = ((a.get("most_recent_instance") or {}).get("location") or {}) if isinstance(a.get("most_recent_instance"), dict) else {}
            out["codeScanning"].append(
                {
                    "number": a.get("number"),
                    "severity": (rule.get("security_severity_level") or rule.get("severity")) if isinstance(rule, dict) else None,
                    "rule": (rule.get("id") if isinstance(rule, dict) else None),
                    "description": _cap(str(rule.get("description") or "") if isinstance(rule, dict) else "", 200),
                    "path": (loc.get("path") if isinstance(loc, dict) else None),
                    "createdAt": a.get("created_at"),
                    "url": a.get("html_url"),
                }
            )
    return out


def _clean_labels(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    labels: list[str] = []
    for lb in raw:
        text = str(lb or "").strip()[:50]
        if text and text not in labels:
            labels.append(text)
    return labels[:10]


def _require_write_token() -> None:
    if not write_enabled():
        raise GitHubSnapshotError(
            "GitHub writes need a token: replace the dummy value in the "
            "lxsoftware-siutindei-board-github-token secret with a fine-grained token "
            "that has issues: write on the repository"
        )


def op_create_issue(args: dict[str, Any]) -> dict[str, Any]:
    _require_write_token()
    repo = repo_full_name()
    title = " ".join(str(args.get("title") or "").split())[:200]
    if not title:
        raise GitHubSnapshotError("title is required")
    body = str(args.get("body") or "").strip()[:MAX_ISSUE_BODY_CHARS]
    payload: dict[str, Any] = {"title": title, "body": body}
    labels = _clean_labels(args.get("labels"))
    if labels:
        payload["labels"] = labels
    created = _request("POST", f"/repos/{repo}/issues", body=payload)
    if not isinstance(created, dict):
        raise GitHubSnapshotError("GitHub did not return the created issue")
    return {"ok": True, "number": created.get("number"), "url": created.get("html_url"), "title": title}


def op_comment_issue(args: dict[str, Any]) -> dict[str, Any]:
    _require_write_token()
    repo = repo_full_name()
    number = _issue_number(args.get("number"))
    body = str(args.get("body") or "").strip()[:MAX_ISSUE_BODY_CHARS]
    if not body:
        raise GitHubSnapshotError("body is required")
    created = _request("POST", f"/repos/{repo}/issues/{number}/comments", body={"body": body})
    if not isinstance(created, dict):
        raise GitHubSnapshotError("GitHub did not return the created comment")
    return {"ok": True, "number": number, "commentId": created.get("id"), "url": created.get("html_url")}


def op_set_labels(args: dict[str, Any]) -> dict[str, Any]:
    _require_write_token()
    repo = repo_full_name()
    number = _issue_number(args.get("number"))
    labels = _clean_labels(args.get("labels"))
    updated = _request("PUT", f"/repos/{repo}/issues/{number}/labels", body={"labels": labels})
    names = [str(lb.get("name")) for lb in updated if isinstance(lb, dict)] if isinstance(updated, list) else labels
    return {"ok": True, "number": number, "labels": names}
