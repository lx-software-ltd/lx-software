"""Shared unittest stubs for the admin Lambda.

New tests should import ``install_aws_stubs`` and ``FakeTable`` from here.
Existing test modules keep their own copies.
"""

from __future__ import annotations

import re
import sys
import types
from typing import Any
from unittest.mock import MagicMock


def install_aws_stubs() -> None:
    """Install MagicMock boto3 and a minimal botocore package before imports."""
    if "boto3" not in sys.modules or not isinstance(sys.modules["boto3"], MagicMock):
        sys.modules["boto3"] = MagicMock()
    if "botocore.exceptions" not in sys.modules:
        botocore = types.ModuleType("botocore")
        exceptions = types.ModuleType("botocore.exceptions")

        class BotoCoreError(Exception):
            pass

        class ClientError(BotoCoreError):
            pass

        exceptions.BotoCoreError = BotoCoreError
        exceptions.ClientError = ClientError
        botocore.exceptions = exceptions
        sys.modules["botocore"] = botocore
        sys.modules["botocore.exceptions"] = exceptions
    elif not hasattr(sys.modules["botocore.exceptions"], "BotoCoreError"):

        class BotoCoreError(Exception):
            pass

        sys.modules["botocore.exceptions"].BotoCoreError = BotoCoreError
    _install_botocore_config_stub()


def _install_botocore_config_stub() -> None:
    if "botocore.config" in sys.modules and hasattr(sys.modules["botocore.config"], "Config"):
        return
    botocore = sys.modules.get("botocore")
    if botocore is None or not isinstance(botocore, types.ModuleType):
        botocore = types.ModuleType("botocore")
        sys.modules["botocore"] = botocore
    botocore.__path__ = []  # type: ignore[attr-defined]
    config = types.ModuleType("botocore.config")

    class Config:
        def __init__(self, **kwargs: Any) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    config.Config = Config
    botocore.config = config
    sys.modules["botocore.config"] = config


class FakeTable:
    """In-memory stand-in for a DynamoDB Table resource."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.scan_calls: list[dict[str, Any]] = []

    @staticmethod
    def _key(item: dict[str, Any]) -> tuple[str, str]:
        return (str(item["pk"]), str(item["sk"]))

    def get_item(self, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        item = self.items.get(self._key(Key))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.items[self._key(Item)] = dict(Item)
        return {}

    def delete_item(self, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.items.pop(self._key(Key), None)
        return {}

    def query(self, **kwargs: Any) -> dict[str, Any]:
        pk_attr, sk_attr = ("gsi1pk", "gsi1sk") if kwargs.get("IndexName") == "gsi1" else ("pk", "sk")
        values = kwargs.get("ExpressionAttributeValues") or {}
        expression = str(kwargs.get("KeyConditionExpression") or "")
        pk_value = None
        prefix = None
        for clause in (part.strip() for part in expression.split(" AND ")):
            equal = re.fullmatch(r"(\w+) = (:\w+)", clause)
            if equal:
                pk_value = values[equal.group(2)]
                continue
            begins = re.fullmatch(r"begins_with\((\w+), (:\w+)\)", clause)
            if begins:
                prefix = values[begins.group(2)]
        rows = [
            dict(item)
            for item in self.items.values()
            if item.get(pk_attr) == pk_value and (prefix is None or str(item.get(sk_attr, "")).startswith(str(prefix)))
        ]
        if kwargs.get("ScanIndexForward") is False:
            rows.reverse()
        limit = kwargs.get("Limit")
        if isinstance(limit, int):
            rows = rows[:limit]
        return {"Items": rows}

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        self.scan_calls.append(kwargs)
        return {"Items": [dict(item) for item in self.items.values()]}
