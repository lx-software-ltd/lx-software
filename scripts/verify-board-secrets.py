#!/usr/bin/env python3
"""Check Executive Board Secrets Manager entries without printing values.

Reads the live ``lxsoftware`` stack parameters (the ARNs CDK will inject)
and the conventional secret *names* the CloudShell wizard uses. For each
secret it fetches the value, checks the shape AdminApiFn expects, and
reports OK / missing / not wired / bad format.

Run in AWS CloudShell (root or admin):

  curl -fsSL https://raw.githubusercontent.com/lx-software-ltd/lx-software/main/scripts/verify-board-secrets.py \\
    -o verify-board-secrets.py
  python3 verify-board-secrets.py

Or from this repo: ``python3 scripts/verify-board-secrets.py``.

Exit 1 if anything required is missing or malformed. Optional tools
(GitHub writes, Brave, Meta, stores, web, finance) print WARN when unset.
Never prints a secret value.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_REGION = "ap-southeast-1"
DEFAULT_STACK = "lxsoftware"

# Conventional names created by setup-board-cloudshell.sh
NAME_GITHUB = "lxsoftware-admin-github-read-token"
NAME_SEARCH = "lxsoftware-admin-search-api-key"
NAME_META_TOKEN = "lxsoftware-admin-meta-board-token"
NAME_META_APP = "lxsoftware-admin-meta-app-secret"
NAME_ASC = "lxsoftware-admin-app-store-connect-key"
NAME_PLAY = "lxsoftware-admin-google-play-sa"
NAME_GA = "lxsoftware-admin-google-analytics-sa"
NAME_OPENROUTER = "lxsoftware-admin-openrouter-api-secret"


@dataclass(frozen=True)
class Check:
    label: str
    stack_param: str
    conventional_name: str
    required: bool
    validate: Callable[[str], list[str]]
    tools: str


def _plain_or_json_token(raw: str, prefixes: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    text = raw.strip()
    if not text:
        return ["empty"]
    token = text
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return ["not valid JSON (starts with '{')"]
        if not isinstance(payload, dict):
            return ["JSON must be an object"]
        token = ""
        for key in (
            "openrouter_api_key",
            "OPENROUTER_API_KEY",
            "github_token",
            "GITHUB_TOKEN",
            "api_key",
            "key",
            "token",
        ):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                token = candidate.strip()
                break
        if not token:
            return ["JSON object has no token field (api_key / token / github_token / …)"]
    if prefixes and not any(token.startswith(p) for p in prefixes):
        errors.append(f"value does not start with {' / '.join(prefixes)} (still usable if this is a valid token)")
    if len(token) < 8:
        errors.append("value is shorter than 8 characters")
    return errors


def validate_openrouter(raw: str) -> list[str]:
    return [e for e in _plain_or_json_token(raw) if "does not start with" not in e]


def validate_github(raw: str) -> list[str]:
    return _plain_or_json_token(raw, prefixes=("github_pat_", "ghp_", "gho_"))


def validate_search(raw: str) -> list[str]:
    return [e for e in _plain_or_json_token(raw) if "does not start with" not in e]


def validate_meta_token(raw: str) -> list[str]:
    return _plain_or_json_token(raw, prefixes=("EAA", "eaa"))


def validate_meta_app_secret(raw: str) -> list[str]:
    return [e for e in _plain_or_json_token(raw) if "does not start with" not in e]


def validate_asc(raw: str) -> list[str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ["must be JSON {keyId, issuerId, privateKey}"]
    if not isinstance(payload, dict):
        return ["must be a JSON object"]
    errors: list[str] = []
    key_id = str(payload.get("keyId") or payload.get("kid") or "").strip()
    issuer = str(payload.get("issuerId") or payload.get("iss") or "").strip()
    pem = str(payload.get("privateKey") or payload.get("p8") or payload.get("key") or "").strip()
    if not key_id:
        errors.append("missing keyId")
    if not issuer:
        errors.append("missing issuerId")
    if not pem:
        errors.append("missing privateKey")
    elif "BEGIN" not in pem or "PRIVATE KEY" not in pem:
        errors.append("privateKey does not look like a PEM (.p8) block")
    return errors


def validate_google_sa(raw: str) -> list[str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ["must be the GCP service-account JSON object"]
    if not isinstance(payload, dict):
        return ["must be a JSON object"]
    errors: list[str] = []
    email = str(payload.get("client_email") or payload.get("clientEmail") or "").strip()
    pem = str(payload.get("private_key") or payload.get("privateKey") or "").strip()
    if not email or "@" not in email:
        errors.append("missing client_email")
    if not pem:
        errors.append("missing private_key")
    elif "BEGIN" not in pem:
        errors.append("private_key does not look like a PEM block")
    return errors


def validate_db(raw: str) -> list[str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ["must be JSON {username, password} (RDS-style)"]
    if not isinstance(payload, dict):
        return ["must be a JSON object"]
    errors: list[str] = []
    if not str(payload.get("username") or "").strip():
        errors.append("missing username")
    if not str(payload.get("password") or "").strip():
        errors.append("missing password")
    return errors


CHECKS: tuple[Check, ...] = (
    Check("OpenRouter API key", "OpenRouterApiKeySecretArn", NAME_OPENROUTER, True, validate_openrouter, "board chat/meetings + statement PDF parse"),
    Check("GitHub PAT", "GitHubReadTokenSecretArn", NAME_GITHUB, False, validate_github, "GitHub writes + security alerts + rate limit"),
    Check("Brave Search API key", "SearchApiKeySecretArn", NAME_SEARCH, False, validate_search, "research (else OpenRouter :online)"),
    Check("Meta System User token", "MetaBoardTokenSecretArn", NAME_META_TOKEN, False, validate_meta_token, "meta tools + webhook writes"),
    Check("Meta app secret", "MetaAppSecretSecretArn", NAME_META_APP, False, validate_meta_app_secret, "POST /webhooks/meta HMAC"),
    Check("App Store Connect key", "AppStoreConnectKeySecretArn", NAME_ASC, False, validate_asc, "stores (Apple)"),
    Check("Google Play service account", "GooglePlayServiceAccountSecretArn", NAME_PLAY, False, validate_google_sa, "stores (Play)"),
    Check("GA4 / GTM service account", "GoogleAnalyticsServiceAccountSecretArn", NAME_GA, False, validate_google_sa, "web tools"),
    Check("Siutindei DB credentials", "SiutindeiDbSecretArn", "", False, validate_db, "finance + product (RDS Data API)"),
)

STACK_FLAGS: tuple[tuple[str, str, bool], ...] = (
    ("MetaVerifyToken", "Meta webhook handshake (not a Secrets Manager secret)", False),
    ("MetaPageId", "Facebook Page id", False),
    ("MetaIgUserId", "Instagram professional-account id", False),
    ("MetaWaPhoneNumberId", "WhatsApp Cloud API phone-number id", False),
    ("MetaAdAccountId", "Meta ad account id", False),
    ("AppStoreConnectAppId", "ASC app id (or inside the ASC secret)", False),
    ("AppStoreConnectVendorNumber", "ASC vendor number (Apple downloads)", False),
    ("GooglePlayPackageName", "Play package name (or inside the Play secret)", False),
    ("Ga4PropertyIds", "GA4 property ids (or inside the GA secret)", False),
    ("GtmContainers", "GTM account:container pairs (or inside the GA secret)", False),
    ("BoardAwsLambdaNames", "Lambda names for aws_lambda_health", False),
    ("SiutindeiClusterArn", "Aurora cluster ARN for Data API", False),
)


class VerifyError(RuntimeError):
    pass


def aws_json(aws: str, region: str, *args: str) -> Any:
    cmd = [aws, "--region", region, *args, "--output", "json"]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise VerifyError("aws CLI not found — run this in CloudShell or install aws") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise VerifyError(err or f"aws {' '.join(args)} failed ({proc.returncode})")
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def aws_json_or_none(aws: str, region: str, *args: str) -> Any:
    try:
        return aws_json(aws, region, *args)
    except VerifyError:
        return None


def stack_params(aws: str, region: str, stack: str) -> dict[str, str]:
    data = aws_json(aws, region, "cloudformation", "describe-stacks", "--stack-name", stack)
    stacks = (data or {}).get("Stacks") or []
    if not stacks:
        raise VerifyError(f"stack {stack} not found")
    out: dict[str, str] = {}
    for row in stacks[0].get("Parameters") or []:
        key = str(row.get("ParameterKey") or "")
        value = str(row.get("ParameterValue") or "")
        if key:
            out[key] = value
    return out


def describe_secret(aws: str, region: str, secret_id: str) -> dict[str, Any] | None:
    return aws_json_or_none(aws, region, "secretsmanager", "describe-secret", "--secret-id", secret_id)


def get_secret_string(aws: str, region: str, secret_id: str) -> str | None:
    data = aws_json_or_none(aws, region, "secretsmanager", "get-secret-value", "--secret-id", secret_id)
    if not data:
        return None
    text = data.get("SecretString")
    if isinstance(text, str):
        return text
    return None


def find_named_secret(aws: str, region: str, name_prefix: str) -> tuple[str, str] | None:
    """Return (name, arn) if a secret whose name starts with name_prefix exists."""
    if not name_prefix:
        return None
    data = aws_json_or_none(
        aws,
        region,
        "secretsmanager",
        "list-secrets",
        "--filters",
        f"Key=name,Values={name_prefix}",
    )
    for row in (data or {}).get("SecretList") or []:
        name = str(row.get("Name") or "")
        arn = str(row.get("ARN") or "")
        if name == name_prefix or name.startswith(name_prefix):
            return name, arn
    # list filter is a prefix match; also try exact describe
    desc = describe_secret(aws, region, name_prefix)
    if desc:
        return str(desc.get("Name") or name_prefix), str(desc.get("ARN") or "")
    return None


def check_one(
    check: Check,
    params: dict[str, str],
    aws: str,
    region: str,
) -> dict[str, Any]:
    wired = (params.get(check.stack_param) or "").strip()
    named = find_named_secret(aws, region, check.conventional_name) if check.conventional_name else None
    secret_id = wired or (named[1] if named else "")
    row: dict[str, Any] = {
        "label": check.label,
        "param": check.stack_param,
        "required": check.required,
        "tools": check.tools,
        "wired": bool(wired),
        "status": "missing",
        "detail": "",
    }
    if not secret_id:
        row["detail"] = "no stack ARN and no secret with the conventional name"
        return row
    raw = get_secret_string(aws, region, secret_id)
    if raw is None:
        row["status"] = "unreadable"
        row["detail"] = "GetSecretValue failed (missing or no permission)"
        return row
    errors = check.validate(raw)
    blocking = [e for e in errors if "does not start with" not in e]
    hints = [e for e in errors if "does not start with" in e]
    if blocking:
        row["status"] = "bad-format"
        row["detail"] = "; ".join(blocking)
        return row
    if wired:
        row["status"] = "ok"
        row["detail"] = "wired to the stack" + (f"; note: {hints[0]}" if hints else "")
    else:
        row["status"] = "not-wired"
        row["detail"] = (
            f"secret exists as {named[0] if named else secret_id} but "
            f"{check.stack_param} is empty on the stack — put the ARN in "
            "params/production.json and CDK-deploy"
        )
        if hints:
            row["detail"] += f"; note: {hints[0]}"
    return row


def render(rows: list[dict[str, Any]], flags: list[tuple[str, str, str]]) -> str:
    lines = ["Executive Board secrets", ""]
    width = max(len(r["label"]) for r in rows)
    for row in rows:
        status = row["status"]
        mark = {
            "ok": "OK  ",
            "not-wired": "WARN",
            "missing": "MISS" if not row["required"] else "FAIL",
            "unreadable": "FAIL",
            "bad-format": "FAIL",
        }.get(status, status.upper()[:4])
        if row["required"] and status == "missing":
            mark = "FAIL"
        lines.append(f"  {mark}  {row['label']:<{width}}  {row['detail'] or status}")
        lines.append(f"        param {row['param']}  ({row['tools']})")
    if flags:
        lines.append("")
        lines.append("Stack parameters (not secrets):")
        fw = max(len(name) for name, _t, _s in flags)
        for name, title, state in flags:
            mark = "SET " if state == "set" else "empty"
            lines.append(f"  {mark}  {name:<{fw}}  {title}")
    return "\n".join(lines) + "\n"


def failed(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        if row["status"] in {"unreadable", "bad-format"}:
            return True
        if row["required"] and row["status"] != "ok":
            return True
    return False


def cmd_verify(args: argparse.Namespace) -> int:
    aws = args.aws
    region = args.region
    try:
        params = stack_params(aws, region, args.stack)
    except VerifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    rows = [check_one(c, params, aws, region) for c in CHECKS]
    flags: list[tuple[str, str, str]] = []
    for name, title, _req in STACK_FLAGS:
        value = (params.get(name) or "").strip()
        flags.append((name, title, "set" if value else "empty"))
    print(render(rows, flags))
    if failed(rows):
        print("Required secrets are missing or malformed. Optional MISS/WARN rows are tools that stay 'not configured' until you add them.")
        return 1
    print("Required secrets look fine. WARN/MISS rows are optional tools.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--stack", default=DEFAULT_STACK)
    parser.add_argument("--aws", default="aws", help="aws CLI binary (for tests)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return cmd_verify(args)
    except VerifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
