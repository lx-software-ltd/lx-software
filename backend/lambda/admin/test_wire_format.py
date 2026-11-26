"""The shared wire-format cases, and the rule that HTTP tests go through the helper."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import wire_format

_CASES = Path(__file__).resolve().parents[3] / "contracts" / "wire-format-cases.json"
_ADMIN = Path(__file__).resolve().parent
_ALLOWED = (
    "inbound_email_handler.lambda_handler(",
    "handler_mod.lambda_handler(",
)


class WireFormatCasesTest(unittest.TestCase):
    def test_shared_cases_round_trip(self) -> None:
        document = json.loads(_CASES.read_text(encoding="utf-8"))
        contract = document["contract"]
        self.assertEqual(len(set(contract["renames"].values())), len(contract["renames"]))
        for case in document["cases"]:
            route = case.get("route", "")
            wire = wire_format.to_wire(case["value"], contract, route)
            self.assertEqual(wire, case["wire"], case["name"])
            self.assertEqual(wire_format.from_wire(wire, contract, route), case["value"], case["name"])

    def test_map_field_data_keys_are_not_camelized(self) -> None:
        contract = json.loads((_ADMIN / "contracts" / "wire-format.json").read_text(encoding="utf-8"))
        got = wire_format.from_wire(
            {"hold_overrides": {"2026-11-26": {"note_text": "a"}, "place_id_1": 1}},
            contract,
        )
        self.assertEqual(set(got["holdOverrides"]), {"2026-11-26", "place_id_1"})

    def test_camel_and_snake_are_inverses(self) -> None:
        contract: dict[str, Any] = {
            "renames": {},
            "verbatimKeys": [],
            "mapFields": {},
            "opaqueFields": [],
            "rootMaps": {},
        }
        for key in ("s3Key", "top10Items", "portfolioSize", "shareFlows"):
            wire = next(iter(wire_format.to_wire({key: 1}, contract)))
            back = next(iter(wire_format.from_wire({wire: 1}, contract)))
            self.assertEqual(back, key)

    def test_only_the_helper_calls_the_http_handler(self) -> None:
        for path in _ADMIN.glob("test_*.py"):
            if path.name == "test_wire_format.py":
                continue
            needle = "lambda" + "_handler("
            for line in path.read_text(encoding="utf-8").splitlines():
                if needle not in line:
                    continue
                if any(token in line for token in _ALLOWED):
                    continue
                self.fail(f"{path.name} calls the HTTP handler directly: {line.strip()}")
