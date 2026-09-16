"""Executive Board ``security`` tool: GitHub + AWS findings, Cognito MFA.

Reads are cached and refreshed hourly. The only write is
``security_open_remediation``, which opens a GitHub issue (always
``propose`` until the founder approves). The board never changes IAM,
Security Hub, or Cognito.

See docs/architecture/executive-board.md §6 (Connectors, ``security``).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

import board_github
import board_store
from http_common import _log_event

FINDINGS_CACHE = "security:findings"
COGNITO_CACHE = "security:cognito"
GITHUB_CACHE = "security:github"


class SecurityToolError(RuntimeError):
    """User-facing failure while reading a security API."""


def _client(service: str, *, region: str | None = None) -> Any:
    kwargs: dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    return boto3.client(service, **kwargs)


def user_pool_id() -> str:
    return (os.environ.get("USER_POOL_ID") or "").strip()


def _cached(table: Any, name: str) -> dict[str, Any] | None:
    hit = board_store.get_cache(table, name)
    if not hit:
        return None
    payload = hit.get("payload")
    if not isinstance(payload, dict):
        return None
    return {**payload, "cached": True, "fetchedAt": hit.get("fetchedAt")}


def _store(table: Any, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = board_store.put_cache(table, name, payload)
    return {**payload, "cached": False, "fetchedAt": doc.get("fetchedAt")}


def fetch_github_alerts(limit: int = 20) -> dict[str, Any]:
    out = board_github.op_list_security_alerts({"limit": limit})
    repo = board_github.repo_full_name()
    secrets: list[dict[str, Any]] = []
    try:
        raw = board_github._get(f"/repos/{repo}/secret-scanning/alerts?state=open&per_page={limit}")
    except board_github.GitHubSnapshotError as exc:
        out.setdefault("notes", []).append(f"Secret scanning unavailable: {exc}")
        raw = None
    if isinstance(raw, list):
        for a in raw:
            if not isinstance(a, dict):
                continue
            secrets.append(
                {
                    "number": a.get("number"),
                    "secretType": a.get("secret_type_display_name") or a.get("secret_type"),
                    "state": a.get("state"),
                    "createdAt": a.get("created_at"),
                    "url": a.get("html_url"),
                }
            )
    elif raw is None and not any("Secret scanning" in n for n in out.get("notes") or []):
        out.setdefault("notes", []).append("Secret scanning alerts are not enabled or not visible.")
    out["secretScanning"] = secrets
    out["openCount"] = (
        len(out.get("dependabot") or [])
        + len(out.get("codeScanning") or [])
        + len(secrets)
    )
    return out


def fetch_hub_findings(limit: int = 25) -> dict[str, Any]:
    try:
        resp = _client("securityhub").get_findings(
            Filters={
                "RecordState": [{"Value": "ACTIVE", "Comparison": "EQUALS"}],
                "WorkflowStatus": [{"Value": "NEW", "Comparison": "EQUALS"}],
                "SeverityLabel": [
                    {"Value": "CRITICAL", "Comparison": "EQUALS"},
                    {"Value": "HIGH", "Comparison": "EQUALS"},
                ],
            },
            MaxResults=min(max(1, limit), 50),
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("InvalidAccessException", "AccessDeniedException"):
            return {"findings": [], "note": "Security Hub is not enabled in this region."}
        raise SecurityToolError(f"Security Hub: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    findings = []
    for f in resp.get("Findings") or []:
        sev = (f.get("Severity") or {}).get("Label")
        findings.append(
            {
                "id": f.get("Id"),
                "title": str(f.get("Title") or "")[:200],
                "severity": sev,
                "product": f.get("ProductName"),
                "resource": ((f.get("Resources") or [{}])[0] or {}).get("Id"),
                "updatedAt": str(f.get("UpdatedAt") or "")[:25],
            }
        )
    return {"count": len(findings), "findings": findings}


def fetch_access_analyzer(limit: int = 25) -> dict[str, Any]:
    try:
        analyzers = _client("accessanalyzer").list_analyzers().get("analyzers") or []
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("AccessDeniedException",):
            return {"findings": [], "note": "IAM Access Analyzer is not available."}
        raise SecurityToolError(f"Access Analyzer: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    if not analyzers:
        return {"findings": [], "note": "No Access Analyzer is configured."}
    arn = analyzers[0].get("arn")
    try:
        resp = _client("accessanalyzer").list_findings(analyzerArn=arn, maxResults=min(max(1, limit), 50))
    except ClientError as exc:
        raise SecurityToolError(f"Access Analyzer findings: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    findings = []
    for fid in resp.get("findings") or []:
        findings.append(
            {
                "id": fid.get("id"),
                "status": fid.get("status"),
                "resourceType": fid.get("resourceType"),
                "resource": fid.get("resource"),
                "principal": ((fid.get("principal") or {}) if isinstance(fid.get("principal"), dict) else {}),
                "updatedAt": str(fid.get("updatedAt") or "")[:25],
            }
        )
    return {"analyzerArn": arn, "count": len(findings), "findings": findings}


def _metric_sum(results: list[dict[str, Any]], metric_id: str) -> int | None:
    for row in results:
        if row.get("Id") != metric_id:
            continue
        values = row.get("Values") or []
        if not values:
            return 0
        return int(round(sum(float(v or 0) for v in values)))
    return None


def fetch_cognito_sign_in_metrics(pool_id: str) -> dict[str, Any]:
    """24h ``AWS/Cognito`` sign-in counters via a Metrics Insights query.

    Cognito publishes ``SignInSuccesses`` and ``SignInThrottles`` per
    (UserPool, UserPoolClient); the ``SELECT`` aggregates across clients so
    the read does not need to know the app-client ids. There is no
    CloudWatch metric for failed sign-ins, and the per-user
    ``AdminListUserAuthEvents`` API is neither granted nor PII-free, so
    ``failedSignIns`` is always ``null``.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    safe_pool = pool_id.replace("'", "")
    schema = 'SCHEMA("AWS/Cognito", UserPool,UserPoolClient)'
    # Metrics Insights allows only one SQL query per GetMetricData call.
    queries = [
        {
            "Id": "signInThrottles",
            "Expression": f"SELECT SUM(SignInThrottles) FROM {schema} WHERE UserPool = '{safe_pool}'",
            "Period": 3600,
        },
        {
            "Id": "signInSuccesses",
            "Expression": f"SELECT SUM(SignInSuccesses) FROM {schema} WHERE UserPool = '{safe_pool}'",
            "Period": 3600,
        },
    ]
    out: dict[str, Any] = {
        "failedSignIns": None,
        "signInThrottles24h": None,
        "signInSuccesses24h": None,
        "note": (
            "Cognito publishes no failed-sign-in metric; signInThrottles24h and signInSuccesses24h come from "
            "CloudWatch AWS/Cognito. Per-user auth events are not read (PII)."
        ),
    }
    results: list[dict[str, Any]] = []
    failed = ""
    cw = _client("cloudwatch")
    for query in queries:
        try:
            resp = cw.get_metric_data(MetricDataQueries=[query], StartTime=start, EndTime=end)
        except ClientError as exc:
            failed = str(exc.response.get("Error", {}).get("Message", exc))[:160]
            _log_event("warning", tag="board_security_cognito_metrics_failed", error=failed)
            continue
        results.extend(resp.get("MetricDataResults") or [])
    if failed and not results:
        out["note"] = f"CloudWatch AWS/Cognito metrics unavailable: {failed}. Failed sign-ins are not measured."
        return out
    out["signInThrottles24h"] = _metric_sum(results, "signInThrottles")
    out["signInSuccesses24h"] = _metric_sum(results, "signInSuccesses")
    return out


def fetch_cognito() -> dict[str, Any]:
    pool_id = user_pool_id()
    if not pool_id:
        return {"note": "USER_POOL_ID is not set on AdminApiFn; Cognito posture is unavailable."}
    try:
        pool = _client("cognito-idp").describe_user_pool(UserPoolId=pool_id).get("UserPool") or {}
    except ClientError as exc:
        raise SecurityToolError(f"Cognito: {exc.response.get('Error', {}).get('Message', exc)}") from exc
    schema = pool.get("SchemaAttributes") or []
    mfa = pool.get("MfaConfiguration") or "OFF"
    # ``UserPoolTier`` is a plain string (LITE | ESSENTIALS | PLUS) on modern pools;
    # ``UserPoolAddOns`` is an optional dict on pools with threat protection.
    tier = pool.get("UserPoolTier")
    add_ons = pool.get("UserPoolAddOns")
    advanced_mode = add_ons.get("AdvancedSecurityMode") if isinstance(add_ons, dict) else None
    sign_ins = fetch_cognito_sign_in_metrics(pool_id)
    return {
        "userPoolId": pool_id,
        "mfa": mfa,
        "tier": tier if isinstance(tier, str) else None,
        "advancedSecurityMode": advanced_mode if isinstance(advanced_mode, str) else None,
        "estimatedUsers": pool.get("EstimatedNumberOfUsers"),
        "passwordPolicy": {
            "minLength": (pool.get("Policies") or {}).get("PasswordPolicy", {}).get("MinimumLength"),
            "requireMfa": mfa in ("ON", "OPTIONAL"),
        },
        "customAttributes": len(schema),
        "failedSignIns": sign_ins["failedSignIns"],
        "signInThrottles24h": sign_ins["signInThrottles24h"],
        "signInSuccesses24h": sign_ins["signInSuccesses24h"],
        "note": sign_ins["note"],
    }


def fetch_findings_bundle() -> dict[str, Any]:
    hub = fetch_hub_findings()
    analyzer = fetch_access_analyzer()
    return {
        "securityHub": hub,
        "accessAnalyzer": analyzer,
        "openHighOrCritical": int(hub.get("count") or 0) + int(analyzer.get("count") or 0),
    }


def refresh_caches(table: Any) -> dict[str, str]:
    notes: dict[str, str] = {}
    for name, fn in (
        (FINDINGS_CACHE, fetch_findings_bundle),
        (COGNITO_CACHE, fetch_cognito),
        (GITHUB_CACHE, lambda: fetch_github_alerts(20)),
    ):
        try:
            _store(table, name, fn())
            notes[name] = "ok"
        except (SecurityToolError, board_github.GitHubSnapshotError, ClientError) as exc:
            notes[name] = str(exc)[:200]
            _log_event("warning", tag="board_security_refresh_failed", key=name, error=str(exc)[:200])
    return notes


def _read(table: Any, name: str, fetcher: Any) -> dict[str, Any]:
    cached = _cached(table, name)
    if cached:
        return cached
    try:
        return _store(table, name, fetcher())
    except ClientError as exc:
        raise SecurityToolError(str(exc)[:300]) from exc


def op_github_alerts(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    limit = args.get("limit") or 20
    return _read(ctx.table, GITHUB_CACHE, lambda: fetch_github_alerts(int(limit)))


def op_hub_findings(ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    return _read(ctx.table, FINDINGS_CACHE, fetch_findings_bundle)


def op_cognito(ctx: Any, _args: dict[str, Any]) -> dict[str, Any]:
    return _read(ctx.table, COGNITO_CACHE, fetch_cognito)


def op_open_remediation(_ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    title = " ".join(str(args.get("title") or "").split())[:200]
    body = str(args.get("body") or "").strip()
    if not title or not body:
        raise SecurityToolError("title and body are required")
    labels = args.get("labels") if isinstance(args.get("labels"), list) else ["security"]
    if "security" not in [str(x).lower() for x in labels]:
        labels = ["security", *labels]
    return board_github.op_create_issue({"title": title, "body": body, "labels": labels})


def digest_for_context(table: Any) -> dict[str, Any]:
    findings = _cached(table, FINDINGS_CACHE) or {}
    github = _cached(table, GITHUB_CACHE) or {}
    cognito = _cached(table, COGNITO_CACHE) or {}
    return {
        "openHighOrCritical": findings.get("openHighOrCritical"),
        "githubOpen": github.get("openCount"),
        "mfa": cognito.get("mfa"),
        "fetchedAt": findings.get("fetchedAt") or github.get("fetchedAt"),
    }
