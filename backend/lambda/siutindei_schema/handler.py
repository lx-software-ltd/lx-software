"""Enable-path companion: apply ``receivables.sql`` through the RDS Data API.

CloudFormation custom resource. Create/Update apply the script (idempotent
``IF NOT EXISTS`` / ``CREATE OR REPLACE``). Delete is a no-op — the tables
belong to the siutindei product cluster.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

import boto3
from botocore.exceptions import ClientError

from sql_split import receivables_statements

_RETRYABLE = (
    "HttpEndpointNotEnabledException",
    "DatabaseResumingException",
    "DatabaseUnavailableException",
    "ThrottlingException",
)
# EnableHttpEndpoint returns before the Data API accepts calls; the custom
# resource that runs this handler is created right after it. Keep retrying
# for this long (Lambda timeout is 180 s).
_RETRY_WINDOW_SECONDS = 120


def _is_retryable(code: str, message: str) -> bool:
    if code in _RETRYABLE:
        return True
    # Data API reports a just-enabled endpoint as a plain BadRequest too.
    return code == "BadRequestException" and "httpendpoint" in message.replace(" ", "").lower()


def _env(name: str, fallback: str = "") -> str:
    return (os.environ.get(name) or fallback).strip()


def _secret_username(sm: Any, secret_arn: str) -> str:
    raw = sm.get_secret_value(SecretId=secret_arn).get("SecretString") or "{}"
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    return str(doc.get("username") or "").strip()


def apply_schema(*, cluster_arn: str, secret_arn: str, database: str) -> dict[str, Any]:
    rds = boto3.client("rds-data")
    sm = boto3.client("secretsmanager")
    statements = receivables_statements()
    started = time.monotonic()
    attempt = 0
    while True:
        applied = 0
        try:
            for sql in statements:
                rds.execute_statement(
                    resourceArn=cluster_arn,
                    secretArn=secret_arn,
                    database=database,
                    sql=sql,
                )
                applied += 1
            username = _secret_username(sm, secret_arn)
            if username:
                rds.execute_statement(
                    resourceArn=cluster_arn,
                    secretArn=secret_arn,
                    database=database,
                    sql=f'GRANT board_api TO "{username}"',
                )
            return {"applied": applied, "grantedTo": username}
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code") or ""
            message = exc.response.get("Error", {}).get("Message") or str(exc)
            elapsed = time.monotonic() - started
            if not _is_retryable(code, message) or elapsed > _RETRY_WINDOW_SECONDS:
                raise RuntimeError(
                    f"receivables.sql failed after {applied} statements ({code}): {message[:400]}"
                ) from exc
            print("receivables_retry", code, f"attempt={attempt}", f"elapsed={int(elapsed)}s")
            time.sleep(min(10, 2**attempt))
            attempt += 1


def _cfn_respond(event: dict[str, Any], context: Any, status: str, data: dict[str, Any], reason: str = "") -> None:
    body = json.dumps(
        {
            "Status": status,
            "Reason": (reason or f"See {getattr(context, 'log_stream_name', '')}")[:1024],
            "PhysicalResourceId": event.get("PhysicalResourceId") or "siutindei-receivables-schema",
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": data,
        }
    ).encode()
    req = urllib.request.Request(event["ResponseURL"], data=body, method="PUT")
    req.add_header("Content-Type", "")
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.URLError:
        # CloudFormation still waits the timeout if the ACK is lost; logging
        # is enough — do not raise or the platform retries the whole apply.
        print("cfn_respond_failed", status)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    props = event.get("ResourceProperties") or {}
    cluster_arn = str(props.get("clusterArn") or _env("SIUTINDEI_CLUSTER_ARN"))
    secret_arn = str(props.get("secretArn") or _env("SIUTINDEI_DB_SECRET_ARN"))
    database = str(props.get("database") or _env("SIUTINDEI_DB_NAME") or "siutindei")
    if event.get("RequestType") == "Delete":
        _cfn_respond(event, context, "SUCCESS", {})
        return {"PhysicalResourceId": event.get("PhysicalResourceId") or "siutindei-receivables-schema"}
    try:
        if not cluster_arn or not secret_arn:
            raise RuntimeError("clusterArn and secretArn are required")
        data = apply_schema(cluster_arn=cluster_arn, secret_arn=secret_arn, database=database)
    except Exception as exc:  # noqa: BLE001 — must ACK CloudFormation
        _cfn_respond(event, context, "FAILED", {}, str(exc))
        raise
    _cfn_respond(event, context, "SUCCESS", data)
    return {"PhysicalResourceId": "siutindei-receivables-schema", "Data": data}
