"""Admin API: boto client accessors."""

from __future__ import annotations

from typing import Any

import boto3
import runtime


def _get_lambda_client() -> Any:
    if runtime._lambda_client is None:
        runtime._lambda_client = boto3.client("lambda")
    return runtime._lambda_client


def _get_secretsmanager_client() -> Any:
    if runtime._secretsmanager is None:
        runtime._secretsmanager = boto3.client("secretsmanager")
    return runtime._secretsmanager
