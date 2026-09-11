"""Tests for the receivables schema custom-resource handler."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import handler


class ApplySchemaTests(unittest.TestCase):
    def test_applies_statements_and_grants_master_user(self) -> None:
        rds = MagicMock()
        sm = MagicMock()
        sm.get_secret_value.return_value = {
            "SecretString": json.dumps({"username": "postgres"})
        }

        def clients(name: str, **_kwargs: object) -> MagicMock:
            return rds if name == "rds-data" else sm

        with patch("handler.boto3.client", side_effect=clients):
            result = handler.apply_schema(
                cluster_arn="arn:cluster",
                secret_arn="arn:secret",
                database="siutindei",
            )

        self.assertGreaterEqual(result["applied"], 10)
        self.assertEqual(result["grantedTo"], "postgres")
        last = rds.execute_statement.call_args_list[-1].kwargs
        self.assertEqual(last["sql"], 'GRANT board_api TO "postgres"')
        self.assertEqual(last["resourceArn"], "arn:cluster")
        self.assertEqual(last["secretArn"], "arn:secret")
        self.assertEqual(last["database"], "siutindei")

    def test_delete_acks_without_touching_rds(self) -> None:
        event = {
            "RequestType": "Delete",
            "ResponseURL": "https://example.test/cfn",
            "StackId": "arn:stack",
            "RequestId": "req-1",
            "LogicalResourceId": "ReceivablesSchema",
            "PhysicalResourceId": "siutindei-receivables-schema",
            "ResourceProperties": {},
        }
        with (
            patch("handler.boto3.client") as client,
            patch("handler.urllib.request.urlopen") as urlopen,
        ):
            urlopen.return_value.read.return_value = b""
            out = handler.lambda_handler(event, MagicMock(log_stream_name="log"))
        client.assert_not_called()
        self.assertEqual(out["PhysicalResourceId"], "siutindei-receivables-schema")
        body = json.loads(urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["Status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
