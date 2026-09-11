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
    last_error = ""
    for attempt in range(8):
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
            last_error = exc.response.get("Error", {}).get("Message") or str(exc)
            if code not in _RETRYABLE or attempt == 7:
                raise RuntimeError(
                    f"receivables.sql failed after {applied} statements ({code}): {last_error[:400]}"
                ) from exc
            time.sleep(min(8, 2**attempt))
    raise RuntimeError(f"receivables.sql failed: {last_error[:400]}")


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
