"""Shared unittest stubs for the admin Lambda.

New tests should import ``install_aws_stubs`` and ``FakeTable`` from here.
Existing test modules keep their own copies.
"""

from __future__ import annotations

import re
import sys
import types
from typing import Any, cast
from unittest.mock import MagicMock


class _StubBotoCoreError(Exception):
    pass


class _StubClientError(_StubBotoCoreError):
    pass


class _StubConfig:
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _ExceptionsModule(types.ModuleType):
    BotoCoreError: type[Exception]
    ClientError: type[Exception]


class _ConfigModule(types.ModuleType):
    Config: type[_StubConfig]


class _BotocoreModule(types.ModuleType):
    __path__: list[str]
    exceptions: _ExceptionsModule
    config: _ConfigModule


def install_aws_stubs() -> None:
    """Install MagicMock boto3 and a minimal botocore package before imports."""
    if "boto3" not in sys.modules or not isinstance(sys.modules["boto3"], MagicMock):
        sys.modules["boto3"] = MagicMock()
    if "botocore.exceptions" not in sys.modules:
        exceptions = _ExceptionsModule("botocore.exceptions")
        exceptions.BotoCoreError = _StubBotoCoreError
        exceptions.ClientError = _StubClientError
        botocore = _BotocoreModule("botocore")
        botocore.exceptions = exceptions
        sys.modules["botocore"] = botocore
        sys.modules["botocore.exceptions"] = exceptions
    else:
        exc_mod = sys.modules["botocore.exceptions"]
        if not hasattr(exc_mod, "BotoCoreError"):
            if isinstance(exc_mod, _ExceptionsModule):
                exc_mod.BotoCoreError = _StubBotoCoreError
            else:
                cast(Any, exc_mod).BotoCoreError = _StubBotoCoreError
    _install_botocore_config_stub()


def _install_botocore_config_stub() -> None:
    if "botocore.config" in sys.modules and hasattr(sys.modules["botocore.config"], "Config"):
        return
    botocore = sys.modules.get("botocore")
    if not isinstance(botocore, _BotocoreModule):
        botocore = _BotocoreModule("botocore")
        sys.modules["botocore"] = botocore
    botocore.__path__ = []
    config = _ConfigModule("botocore.config")
    config.Config = _StubConfig
    botocore.config = config
    sys.modules["botocore.config"] = config


def _condition_holds(item: dict[str, Any] | None, expr: str, values: dict[str, Any]) -> bool:
    """The condition shapes ``put_item`` uses. Unknown shapes fail the test."""
    if expr == "attribute_not_exists(pk)":
        return item is None
    if expr == "attribute_not_exists(spendToken)":
        return item is not None and "spendToken" not in item
    if expr == "spendToken = :prev":
        return item is not None and item.get("spendToken") == values.get(":prev")
    if item is None:
        return False
    for part in expr.split(" AND "):
        clause = part.strip()
        if clause == "attribute_exists(accessToken)":
            if not item.get("accessToken"):
                return False
            continue
        equal = re.fullmatch(r"(\w+) = (:\w+)", clause)
        if equal:
            if item.get(equal.group(1)) != values.get(equal.group(2)):
                return False
            continue
        different = re.fullmatch(r"(\w+) <> (:\w+)", clause)
        if different:
            if item.get(different.group(1)) == values.get(different.group(2)):
                return False
            continue
        raise AssertionError(f"FakeTable condition not supported: {expr}")
    return True


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

    def put_item(
        self,
        Item: dict[str, Any],
        ConditionExpression: str | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        key = self._key(Item)
        current = self.items.get(key)
        if ConditionExpression:
            expr = " ".join(ConditionExpression.split())
            values = ExpressionAttributeValues or {}
            conflict = not _condition_holds(current, expr, values)
            if conflict:
                from botocore.exceptions import ClientError

                exc = ClientError(
                    {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}},
                    "PutItem",
                )
                exc.response = {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}}  # type: ignore[attr-defined]
                raise exc
        self.items[key] = dict(Item)
        return {}

    def delete_item(self, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.items.pop(self._key(Key), None)
        return {}

    def update_item(
        self,
        Key: dict[str, Any],
        UpdateExpression: str = "",
        ExpressionAttributeNames: dict[str, str] | None = None,
        ExpressionAttributeValues: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Enough of UpdateItem for ADD and SET clauses used by the usage ledger."""
        key = (str(Key["pk"]), str(Key["sk"]))
        item = dict(self.items.get(key) or {"pk": Key["pk"], "sk": Key["sk"]})
        names = ExpressionAttributeNames or {}
        values = ExpressionAttributeValues or {}
        update_expression = UpdateExpression.strip()
        add_part, _separator, set_part = update_expression.partition("SET")
        if add_part.strip().upper().startswith("ADD"):
            for piece in add_part.strip()[3:].split(","):
                attr, placeholder = piece.split()
                attr = names.get(attr, attr)
                item[attr] = item.get(attr, 0) + values[placeholder]
        if set_part:
            for piece in set_part.split(","):
                left, placeholder = piece.split("=", 1)
                attr = names.get(left.strip(), left.strip())
                item[attr] = values[placeholder.strip()]
        self.items[key] = item
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
        rows.sort(key=lambda item: str(item.get(sk_attr) or ""))
        if kwargs.get("ScanIndexForward", True) is False:
            rows.reverse()
        start = kwargs.get("ExclusiveStartKey")
        if isinstance(start, dict) and start.get(sk_attr):
            passed = False
            kept: list[dict[str, Any]] = []
            for row in rows:
                if passed:
                    kept.append(row)
                elif str(row.get(sk_attr) or "") == str(start.get(sk_attr)):
                    passed = True
            rows = kept
        last_key = None
        limit = kwargs.get("Limit")
        if isinstance(limit, int) and len(rows) > limit:
            last = rows[limit - 1]
            last_key = {key: last[key] for key in (pk_attr, sk_attr, "pk", "sk") if key in last}
            rows = rows[:limit]
        result: dict[str, Any] = {"Items": rows}
        if last_key:
            result["LastEvaluatedKey"] = last_key
        return result

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        self.scan_calls.append(kwargs)
        return {"Items": [dict(item) for item in self.items.values()]}
