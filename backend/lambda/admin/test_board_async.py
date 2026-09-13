"""Unit tests for board_async Event invoke helpers."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import board_async


class TryInvokeEventTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("AWS_LAMBDA_FUNCTION_NAME", None)
        os.environ.pop("PARSE_WORKER_FUNCTION_NAME", None)

    def test_false_when_no_function_name(self) -> None:
        os.environ.pop("AWS_LAMBDA_FUNCTION_NAME", None)
        os.environ.pop("PARSE_WORKER_FUNCTION_NAME", None)
        self.assertFalse(board_async.try_invoke_event({"internal": "board_staff_tick"}))

    def test_true_when_invoke_accepted(self) -> None:
        os.environ["AWS_LAMBDA_FUNCTION_NAME"] = "admin-fn"
        client = MagicMock()
        with patch.object(board_async.boto3, "client", return_value=client) as factory:
            self.assertTrue(board_async.try_invoke_event({"internal": "board_staff_tick"}))
        factory.assert_called_once()
        config = factory.call_args.kwargs["config"]
        self.assertEqual(config.connect_timeout, board_async.INVOKE_EVENT_TIMEOUT_SECONDS)
        self.assertEqual(config.read_timeout, board_async.INVOKE_EVENT_TIMEOUT_SECONDS)
        client.invoke.assert_called_once()
        kwargs = client.invoke.call_args.kwargs
        self.assertEqual(kwargs["FunctionName"], "admin-fn")
        self.assertEqual(kwargs["InvocationType"], "Event")

    def test_false_when_invoke_times_out(self) -> None:
        os.environ["AWS_LAMBDA_FUNCTION_NAME"] = "admin-fn"
        client = MagicMock()
        client.invoke.side_effect = TimeoutError("read timed out")
        with patch.object(board_async.boto3, "client", return_value=client):
            self.assertFalse(board_async.try_invoke_event({"internal": "board_staff_tick"}))


if __name__ == "__main__":
    unittest.main()
