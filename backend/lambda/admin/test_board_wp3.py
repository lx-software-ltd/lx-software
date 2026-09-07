"""WP3: receivables data layer — typed Data API params, invoice numbers,
status guards with match candidates, mirror diffing, exact-day dunning, and
the DSO / per-provider / CPA / margin read tools."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import board_data_api
import board_product
import board_receivables
import board_store
import board_tools
from board_data_api import Date, Numeric, Timestamp, Typed, Uuid
from board_tools import REGISTRY, execute_call
from finance_store import _finance_owner_ddb_key, _load_finance_owner, _normalize_finance_payload
from ddb_convert import _to_ddb_nested
from test_board_t4 import ReceivablesTestCase

SQL_FILE = Path(__file__).resolve().parents[3] / "scripts" / "siutindei" / "receivables.sql"
SMOKE_CLI = Path(__file__).resolve().parents[3] / "scripts" / "siutindei" / "smoke_data_api.py"


def _invoice(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "inv-1",
        "subscription_id": "sub-1",
        "number": "STD-2026-0001",
        "issued_on": "2026-09-01",
        "due_on": "2026-09-15",
        "amount_hkd": 388.0,
        "status": "sent",
        "fps_reference": "STDFPS0001",
        "pdf_key": None,
    }
    base.update(overrides)
    return base


def _payment(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "pay-1",
        "invoice_id": None,
        "received_on": "2026-09-02",
        "amount_hkd": 388.0,
        "payer_name": "Splash",
        "bank_reference": "STDFPS0001",
        "source": "manual",
        "matched_by": None,
    }
    base.update(overrides)
    return base


class TestTypedParameters(unittest.TestCase):
    def test_type_hints_are_emitted_per_parameter(self) -> None:
        emitted = board_data_api.params(
            id=Uuid("0f8fad5b-d9cb-469f-a165-70867728950e"),
            issued=Date(date(2026, 9, 4)),
            when=Timestamp("2026-09-04 10:00:00"),
            amount=Numeric(388.0),
            price=Numeric("3880"),
            status="draft",
            lim=100,
            ratio=0.5,
            missing=Uuid(None),
            plain=None,
        )
        by_name = {p["name"]: p for p in emitted}
        self.assertEqual(by_name["id"], {"name": "id", "value": {"stringValue": "0f8fad5b-d9cb-469f-a165-70867728950e"}, "typeHint": "UUID"})
        self.assertEqual(by_name["issued"], {"name": "issued", "value": {"stringValue": "2026-09-04"}, "typeHint": "DATE"})
        self.assertEqual(by_name["when"]["typeHint"], "TIMESTAMP")
        self.assertEqual(by_name["amount"], {"name": "amount", "value": {"stringValue": "388.00"}, "typeHint": "DECIMAL"})
        self.assertEqual(by_name["price"]["value"], {"stringValue": "3880"})
        self.assertEqual(by_name["status"], {"name": "status", "value": {"stringValue": "draft"}})
        self.assertEqual(by_name["lim"], {"name": "lim", "value": {"longValue": 100}})
        self.assertEqual(by_name["ratio"], {"name": "ratio", "value": {"doubleValue": 0.5}})
        self.assertEqual(by_name["missing"], {"name": "missing", "value": {"isNull": True}})
        self.assertNotIn("typeHint", by_name["missing"])
        self.assertEqual(by_name["plain"], {"name": "plain", "value": {"isNull": True}})

    def test_date_accepts_strings_and_datetimes(self) -> None:
        from datetime import datetime

        self.assertEqual(Date("2026-09-04T12:00:00Z").value, "2026-09-04")
        self.assertEqual(Date(datetime(2026, 9, 4, 8, 30)).value, "2026-09-04")
        self.assertIsInstance(Date(""), Typed)
        self.assertIsNone(Date("").value)

    def test_unique_violation_detection(self) -> None:
        self.assertTrue(board_data_api.is_unique_violation(RuntimeError('duplicate key value violates unique constraint "x"')))
        self.assertTrue(board_data_api.is_unique_violation(RuntimeError("SQLState: 23505")))
        self.assertFalse(board_data_api.is_unique_violation(RuntimeError("relation does not exist")))

    def test_statement_kwargs_include_transaction(self) -> None:
        kwargs = board_data_api.statement_kwargs(
            "SELECT 1", None, resource_arn="arn:c", secret="arn:s", database="db", transaction_id="tx-1"
        )
        self.assertEqual(kwargs["resourceArn"], "arn:c")
        self.assertEqual(kwargs["transactionId"], "tx-1")
        self.assertNotIn("parameters", kwargs)


class TestCallSitesUseTypeHints(ReceivablesTestCase):
    def _hints(self) -> dict[tuple[str, str], str]:
        out: dict[tuple[str, str], str] = {}
        for sql, params in zip(self.db.sqls, self.db.parameters):
            for p in params or []:
                out[(" ".join(sql.split())[:60], p["name"])] = p.get("typeHint", "")
        return out

    def test_draft_invoice_emits_uuid_date_decimal(self) -> None:
        board_receivables.op_draft_invoice(None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "r"})
        insert = next(p for s, p in zip(self.db.sqls, self.db.parameters) if s.startswith("INSERT INTO invoices"))
        hints = {p["name"]: p.get("typeHint") for p in insert}
        self.assertEqual(hints["id"], "UUID")
        self.assertEqual(hints["sub"], "UUID")
        self.assertEqual(hints["issued"], "DATE")
        self.assertEqual(hints["due"], "DATE")
        self.assertEqual(hints["amount"], "DECIMAL")
        self.assertIsNone(hints["number"])
        lookup = next(p for s, p in zip(self.db.sqls, self.db.parameters) if "FROM listing_subscriptions WHERE id" in s)
        self.assertEqual(lookup[0]["typeHint"], "UUID")

    def test_manual_payment_and_plan_emit_hints(self) -> None:
        board_receivables.op_record_manual_payment(None, {"amountHkd": 50, "receivedOn": "2026-09-03", "reason": "r"})
        insert = next(p for s, p in zip(self.db.sqls, self.db.parameters) if s.startswith("INSERT INTO payments"))
        hints = {p["name"]: p.get("typeHint") for p in insert}
        self.assertEqual((hints["id"], hints["received"], hints["amount"]), ("UUID", "DATE", "DECIMAL"))
        self.assertEqual(next(p for p in insert if p["name"] == "inv")["value"], {"isNull": True})
        board_receivables.op_propose_price_change(None, {"name": "Annual", "priceHkd": 3880, "billingPeriod": "annual"})
        plan = next(p for s, p in zip(self.db.sqls, self.db.parameters) if s.startswith("INSERT INTO listing_plans"))
        hints = {p["name"]: p.get("typeHint") for p in plan}
        self.assertEqual((hints["id"], hints["price"]), ("UUID", "DECIMAL"))
        with self.assertRaises(board_receivables.ReceivablesError):
            board_receivables.op_record_manual_payment(None, {"amountHkd": 50, "receivedOn": "yesterday", "reason": "r"})

    def test_funnel_dates_are_typed_and_validated(self) -> None:
        board_product.op_funnel(None, {"from": "2026-09-01", "to": "2026-09-30"})
        params = self.db.parameters[-1] or []
        self.assertEqual({p["name"]: p["typeHint"] for p in params}, {"dfrom": "DATE", "dto": "DATE"})
        with self.assertRaises(board_product.ProductError):
            board_product.op_funnel(None, {"from": "last week"})


class TestInvoiceNumbers(ReceivablesTestCase):
    def test_retries_after_unique_violation(self) -> None:
        year = date.today().year
        self.db.race_invoice_inserts = 1
        out = board_receivables.op_draft_invoice(None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "r"})
        self.assertEqual(out["number"], f"STD-{year}-0002")
        inserts = [s for s in self.db.sqls if s.startswith("INSERT INTO invoices")]
        self.assertEqual(len(inserts), 2)
        numbers = sorted(i["number"] for i in self.db.invoices)
        self.assertEqual(numbers, [f"STD-{year}-0001", f"STD-{year}-0002"])
        mine = next(i for i in self.db.invoices if i["id"] == out["invoiceId"])
        self.assertEqual(mine["fps_reference"], out["fpsReference"])

    def test_gives_up_after_three_attempts(self) -> None:
        self.db.race_invoice_inserts = 3
        with self.assertRaises(board_receivables.ReceivablesError) as ctx:
            board_receivables.op_draft_invoice(None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "r"})
        self.assertIn("duplicate key", str(ctx.exception))
        self.assertEqual(len([s for s in self.db.sqls if s.startswith("INSERT INTO invoices")]), 3)

    def test_other_errors_are_not_retried(self) -> None:
        def boom(sql: str, parameters: Any) -> list[dict[str, Any]]:
            if sql.startswith("INSERT INTO invoices"):
                raise board_data_api.DataApiError("Data API: permission denied for table invoices")
            return self.db(sql, parameters)

        board_data_api.set_executor_for_tests(boom)
        with self.assertRaises(board_receivables.ReceivablesError) as ctx:
            board_receivables.op_draft_invoice(None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "r"})
        self.assertIn("permission denied", str(ctx.exception))


class TestStatusGuards(ReceivablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.ctx = self._ctx(actor="owner")

    def test_send_invoice_requires_draft_or_sent(self) -> None:
        self.db.invoices.append(_invoice(id="inv-paid", status="paid", number="STD-2026-0009"))
        with self.assertRaises(board_receivables.ReceivablesError) as ctx:
            board_receivables.op_send_invoice(self.ctx, {"invoiceId": "inv-paid"})
        self.assertIn("is paid; only draft or sent invoices can be sent", str(ctx.exception))
        self.db.invoices.append(_invoice(id="inv-void", status="void", number="STD-2026-0010"))
        reason = board_receivables.act_guard_send(self.ctx, {"invoiceId": "inv-void"}, op="finance_send_invoice")
        self.assertIn("is void", reason or "")
        self.db.invoices.append(_invoice(id="inv-draft", status="draft", number="STD-2026-0011"))
        out = board_receivables.op_send_invoice(self.ctx, {"invoiceId": "inv-draft"})
        self.assertTrue(out["ok"])
        self.assertEqual(self.db.invoices[-1]["status"], "sent")

    def test_reminder_requires_sent_or_overdue(self) -> None:
        self.db.invoices.append(_invoice(id="inv-draft", status="draft"))
        with self.assertRaises(board_receivables.ReceivablesError) as ctx:
            board_receivables.op_send_reminder(self.ctx, {"invoiceId": "inv-draft"})
        self.assertIn("only sent or overdue invoices can be reminded", str(ctx.exception))
        self.db.invoices.append(_invoice(id="inv-sent", status="sent", number="STD-2026-0002"))
        out = board_receivables.op_send_reminder(self.ctx, {"invoiceId": "inv-sent", "stage": "d7"})
        self.assertEqual(out["stage"], "d7")
        self.assertEqual(self.db.invoices[-1]["status"], "overdue")
        again = board_receivables.op_send_reminder(self.ctx, {"invoiceId": "inv-sent"})
        self.assertTrue(again["ok"])
        self.assertEqual(self.db.invoices[-1]["status"], "overdue")

    def test_match_rejects_paid_void_and_attached_payments(self) -> None:
        self.db.invoices.append(_invoice(id="inv-paid", status="paid"))
        self.db.invoices.append(_invoice(id="inv-open", status="sent", number="STD-2026-0002", fps_reference="STDFPS0002"))
        self.db.payments.append(_payment(id="pay-1"))
        self.db.payments.append(_payment(id="pay-taken", invoice_id="inv-elsewhere", bank_reference="STDFPS0002"))
        with self.assertRaises(board_receivables.ReceivablesError) as ctx:
            board_receivables.op_match_payment(None, {"paymentId": "pay-1", "invoiceId": "inv-paid"})
        self.assertIn("is paid; only draft or sent or overdue invoices can be matched", str(ctx.exception))
        self.assertIsNone(self.db.payments[0]["invoice_id"])
        self.assertIn("is paid", board_receivables.act_guard_match(None, {"paymentId": "pay-1", "invoiceId": "inv-paid"}) or "")
        with self.assertRaises(board_receivables.ReceivablesError) as ctx:
            board_receivables.op_match_payment(None, {"paymentId": "pay-taken", "invoiceId": "inv-open"})
        self.assertIn("already attached to invoice inv-elsewhere", str(ctx.exception))
        self.assertIn("already attached", board_receivables.act_guard_match(None, {"paymentId": "pay-taken", "invoiceId": "inv-open"}) or "")
        # Re-matching the same payment to the invoice it is already on is allowed.
        self.db.payments.append(_payment(id="pay-same", invoice_id="inv-open", amount_hkd=388.0, bank_reference="STDFPS0002"))
        self.assertIsNone(board_receivables.act_guard_match(None, {"paymentId": "pay-same", "invoiceId": "inv-open"}))

    def test_guard_and_op_surface_candidates(self) -> None:
        self.db.invoices.append(_invoice(id="inv-target", status="sent", amount_hkd=500.0, fps_reference="STDTARGET"))
        self.db.invoices.append(_invoice(id="inv-amount", status="overdue", number="STD-2026-0002", amount_hkd=388.005, fps_reference="STDAMOUNT"))
        self.db.invoices.append(_invoice(id="inv-ref", status="draft", number="STD-2026-0003", amount_hkd=900.0, fps_reference="STDFPS0001"))
        self.db.invoices.append(_invoice(id="inv-paid", status="paid", number="STD-2026-0004", amount_hkd=388.0, fps_reference="STDPAID"))
        self.db.payments.append(_payment(id="pay-1", amount_hkd=388.0, bank_reference="stdfps0001"))
        reason = board_receivables.act_guard_match(None, {"paymentId": "pay-1", "invoiceId": "inv-target"})
        self.assertIn("does not agree", reason or "")
        self.assertIn("STD-2026-0002", reason or "")
        self.assertIn("STD-2026-0003", reason or "")
        self.assertNotIn("STD-2026-0004", reason or "")
        out = board_receivables.op_match_payment(None, {"paymentId": "pay-1", "invoiceId": "inv-target"})
        self.assertTrue(out["ok"])
        self.assertFalse(out["amountAgrees"])
        self.assertEqual(out["invoiceStatus"], "sent")
        ids = {c["id"] for c in out["candidates"]}
        self.assertEqual(ids, {"inv-amount", "inv-ref"})
        by_id = {c["id"]: c for c in out["candidates"]}
        self.assertTrue(by_id["inv-amount"]["amountAgrees"])
        self.assertTrue(by_id["inv-ref"]["referenceAgrees"])
        self.assertEqual(self.db.payments[0]["invoice_id"], "inv-target")
        self.assertEqual(next(i for i in self.db.invoices if i["id"] == "inv-target")["status"], "sent")

    def test_exact_match_has_no_candidates_key(self) -> None:
        self.db.invoices.append(_invoice())
        self.db.payments.append(_payment())
        out = board_receivables.op_match_payment(None, {"paymentId": "pay-1", "invoiceId": "inv-1"})
        self.assertNotIn("candidates", out)
        self.assertEqual(out["invoiceStatus"], "paid")

    def test_persona_act_is_downgraded_with_candidates_in_message(self) -> None:
        self.db.invoices.append(_invoice(id="inv-target", amount_hkd=500.0, fps_reference="STDTARGET"))
        self.db.invoices.append(_invoice(id="inv-other", number="STD-2026-0002", fps_reference="STDFPS0001"))
        self.db.payments.append(_payment())
        outcome = execute_call(
            self._ctx(global_mode="act"),
            REGISTRY["finance_match_payment"],
            {"paymentId": "pay-1", "invoiceId": "inv-target", "reason": "Guess."},
        )
        self.assertEqual(outcome.status, "pending_approval")
        self.assertIn("candidates: STD-2026-0002", outcome.result["message"])

    def test_manual_payment_keeps_row_unattached_when_match_is_refused(self) -> None:
        self.db.invoices.append(_invoice(id="inv-paid", status="paid"))
        out = board_receivables.op_record_manual_payment(
            None, {"amountHkd": 388, "invoiceId": "inv-paid", "receivedOn": "2026-09-03", "reason": "r"}
        )
        self.assertTrue(out["ok"])
        self.assertFalse(out["matched"])
        self.assertIn("is paid", out["matchWarning"])
        self.assertIsNone(self.db.payments[0]["invoice_id"])


class TestMirrorDiff(ReceivablesTestCase):
    def _book_ids(self) -> dict[str, dict[str, Any]]:
        return {ln["id"]: ln for ln in _load_finance_owner(self.table, "siuTinDei")["lines"]}

    def test_paid_invoice_drops_its_receivable_line(self) -> None:
        today = date.today().isoformat()
        inv = _invoice(id="inv-1", status="draft", issued_on=today, due_on=today)
        self.db.invoices.append(inv)
        first = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual((first["linesWritten"], first["linesRemoved"]), (0, 0))
        self.assertEqual(self._book_ids(), {})

        inv["status"] = "sent"
        second = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual((second["linesWritten"], second["linesRemoved"]), (1, 0))
        book = self._book_ids()
        self.assertEqual(set(book), {"recv-inv-inv-1"})
        self.assertEqual(book["recv-inv-inv-1"]["source"], "receivables")
        self.assertEqual(book["recv-inv-inv-1"]["type"], "income")

        self.db.payments.append(_payment(id="pay-1", received_on=today))
        board_receivables.op_match_payment(None, {"paymentId": "pay-1", "invoiceId": "inv-1"})
        self.assertEqual(inv["status"], "paid")
        third = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual((third["linesWritten"], third["linesRemoved"]), (1, 1))
        book = self._book_ids()
        self.assertEqual(set(book), {"recv-pay-pay-1"})
        self.assertEqual(book["recv-pay-pay-1"]["source"], "receivables")
        self.assertEqual(book["recv-pay-pay-1"]["grossAmount"], 388.0)

        fourth = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual((fourth["linesWritten"], fourth["linesRemoved"]), (0, 0))
        self.assertEqual(set(self._book_ids()), {"recv-pay-pay-1"})

    def test_manual_lines_and_legacy_untagged_lines_survive(self) -> None:
        today = date.today().isoformat()
        payload = _normalize_finance_payload(
            {
                "defaultCurrency": "HKD",
                "float": {"amount": 0, "currency": "HKD"},
                "lines": [
                    {
                        "id": "manual-1",
                        "dateUtc": f"{today}T00:00:00.000Z",
                        "type": "expenditure",
                        "description": "Domain renewal",
                        "netAmount": 100,
                        "vat": 0,
                        "grossAmount": 100,
                        "currency": "HKD",
                    },
                    {
                        "id": "recv-inv-stale",
                        "dateUtc": f"{today}T00:00:00.000Z",
                        "type": "income",
                        "description": "[receivables] Invoice STD-2025-0001 due 2025-01-01 (sent)",
                        "netAmount": 50,
                        "vat": 0,
                        "grossAmount": 50,
                        "currency": "HKD",
                    },
                ],
            }
        )
        self.table.put_item(Item={**_finance_owner_ddb_key("siuTinDei"), **_to_ddb_nested(payload)})
        self.db.invoices.append(_invoice(id="inv-1", issued_on=today, due_on=today))
        out = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual((out["linesWritten"], out["linesRemoved"]), (1, 1))
        book = self._book_ids()
        self.assertEqual(set(book), {"manual-1", "recv-inv-inv-1"})
        self.assertNotIn("source", book["manual-1"])
        self.assertEqual(book["recv-inv-inv-1"]["source"], "receivables")
        self.assertEqual(board_receivables.mirror_to_statement_book(self.table)["linesWritten"], 0)

    def test_untouched_book_is_not_rewritten(self) -> None:
        self.db.invoices.append(_invoice(id="inv-1", issued_on=date.today().isoformat()))
        board_receivables.mirror_to_statement_book(self.table)
        with patch.object(self.table, "put_item", wraps=self.table.put_item) as put:
            out = board_receivables.mirror_to_statement_book(self.table)
        self.assertEqual(out, {"ok": True, "linesWritten": 0, "linesRemoved": 0})
        put.assert_not_called()


class TestDunningExactDays(ReceivablesTestCase):
    def _overdue(self, inv_id: str, days: int, number: str) -> None:
        due = (date.today() - timedelta(days=days)).isoformat()
        self.db.invoices.append(_invoice(id=inv_id, number=number, issued_on=due, due_on=due, fps_reference=f"FPS{inv_id}"))

    def _run(self) -> dict[str, Any]:
        with patch.object(board_store, "records_table", return_value=self.table):
            return board_receivables.handle_dunning_trigger({})

    def _reminders(self) -> list[dict[str, Any]]:
        return [a for a in board_store.list_approvals(self.table) if a.get("op") == "finance_send_reminder"]

    def test_other_board_key_is_a_no_op(self) -> None:
        self._overdue("inv-21", 21, "STD-2026-0021")
        with patch.object(board_store, "records_table", return_value=self.table):
            out = board_receivables.handle_dunning_trigger({"boardKey": "lxSoftware"})
            mirror = board_receivables.handle_mirror_trigger({"boardKey": "lxSoftware"})
        self.assertEqual(out, {"ok": True, "skipped": "other_board"})
        self.assertEqual(mirror, {"ok": True, "skipped": "other_board"})
        self.assertEqual(self._reminders(), [])

    def test_day_8_and_day_20_do_nothing(self) -> None:
        self._overdue("inv-8", 8, "STD-2026-0008")
        self._overdue("inv-20", 20, "STD-2026-0020")
        out = self._run()
        self.assertEqual(out["created"], 0)
        self.assertEqual(self._reminders(), [])

    def test_day_21_creates_one_stage_tagged_proposal(self) -> None:
        self._overdue("inv-21", 21, "STD-2026-0021")
        self._overdue("inv-35", 35, "STD-2026-0035")
        out = self._run()
        self.assertEqual(out["created"], 2)
        reminders = {a["arguments"]["invoiceId"]: a for a in self._reminders()}
        self.assertEqual(set(reminders), {"inv-21", "inv-35"})
        self.assertEqual(reminders["inv-21"]["arguments"]["stage"], "d21")
        self.assertEqual(reminders["inv-35"]["arguments"]["stage"], "d35")
        # Arguments stay within the finance_send_reminder schema so approval executes.
        self.assertEqual(set(reminders["inv-21"]["arguments"]), {"invoiceId", "stage", "reason"})
        board_tools.validate_arguments(REGISTRY["finance_send_reminder"], reminders["inv-21"]["arguments"])
        self.assertIn("D+21", reminders["inv-21"]["summary"])
        self.assertEqual(reminders["inv-21"]["status"], "pending")
        self.assertEqual(reminders["inv-21"]["context"]["kind"], "schedule")
        again = self._run()
        self.assertEqual((again["created"], again["skipped"]), (0, 2))

    def test_decided_approval_for_same_stage_is_not_requeued(self) -> None:
        self._overdue("inv-21", 21, "STD-2026-0021")
        first = self._run()
        self.assertEqual(first["created"], 1)
        approval = self._reminders()[0]
        settings = board_store.load_settings(self.table)
        with patch.object(board_receivables, "_send_mail", return_value={"ok": True, "sent": True}):
            decided = board_tools.decide_approval(
                self.table, settings, approval["approvalId"], approve=True, owner_sub="owner-1"
            )
        self.assertEqual(decided["status"], "executed", decided.get("errorMessage"))
        self.assertEqual(board_receivables.approval_stage(decided), "d21")
        self.assertEqual(self.db.invoices[0]["status"], "overdue")
        rerun = self._run()
        self.assertEqual((rerun["created"], rerun["skipped"]), (0, 1))
        self.assertEqual(len(self._reminders()), 1)

    def test_rejected_earlier_stage_does_not_block_later_stage(self) -> None:
        self._overdue("inv-21", 21, "STD-2026-0021")
        rejected = board_tools.create_approval(
            board_tools.ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cfo", display_name="CFO"),
            REGISTRY["finance_send_reminder"],
            {"invoiceId": "inv-21", "reason": "Earlier stage."},
            summary="Dunning reminder (D+7) for STD-2026-0021",
        )
        # Rows written before ``stage`` joined the schema carried it top-level.
        board_store.put_approval(self.table, {**rejected, "status": "rejected", "dunningStage": "d7"})
        out = self._run()
        self.assertEqual(out["created"], 1)
        stages = sorted(board_receivables.approval_stage(a) for a in self._reminders())
        self.assertEqual(stages, ["d21", "d7"])
        self.assertEqual(board_receivables.approval_stage({"arguments": {"stage": "d35"}}), "d35")

    def test_pending_reminder_for_invoice_blocks_any_stage(self) -> None:
        self._overdue("inv-21", 21, "STD-2026-0021")
        board_tools.create_approval(
            board_tools.ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cfo", display_name="CFO"),
            REGISTRY["finance_send_reminder"],
            {"invoiceId": "inv-21", "reason": "Legacy proposal without stage."},
            summary="Dunning reminder for STD-2026-0021",
        )
        out = self._run()
        self.assertEqual((out["created"], out["skipped"]), (0, 1))

    def test_max_pending_error_is_logged_not_raised(self) -> None:
        self._overdue("inv-7", 7, "STD-2026-0007")
        self._overdue("inv-21", 21, "STD-2026-0021")
        with patch.object(board_tools, "create_approval", side_effect=board_tools.ToolPermissionError("Too many pending approvals")):
            out = self._run()
        self.assertEqual((out["created"], out["refused"]), (0, 2))
        self.assertEqual(self._reminders(), [])


class TestReadTools(ReceivablesTestCase):
    def test_dso_uses_trailing_90_day_paid_revenue(self) -> None:
        today = date.today()
        self.db.invoices.append(_invoice(id="inv-open", status="sent", amount_hkd=900.0, due_on=today.isoformat()))
        aging = board_receivables.op_aging_report(None, {})
        self.assertEqual(aging["dso"], 0.0)
        self.assertEqual(aging["dsoBasis"], {"windowDays": 90, "paidRevenueHkd": 0.0})
        self.db.invoices.append(_invoice(id="inv-paid", status="paid", number="STD-2026-0002", amount_hkd=1800.0, issued_on=(today - timedelta(days=30)).isoformat()))
        self.db.invoices.append(_invoice(id="inv-old", status="paid", number="STD-2026-0003", amount_hkd=9999.0, issued_on=(today - timedelta(days=120)).isoformat()))
        aging = board_receivables.op_aging_report(None, {})
        # 900 outstanding ÷ (1800 / 90 per day) = 45 days
        self.assertEqual(aging["dso"], 45.0)
        self.assertEqual(aging["dsoBasis"]["paidRevenueHkd"], 1800.0)
        self.assertEqual(aging["outstandingHkd"], 900.0)

    def test_past_due_by_provider_groups_by_organization(self) -> None:
        today = date.today()
        self.db.subs.append(
            {
                "id": "sub-2",
                "organization_id": "org-2",
                "store_id": None,
                "plan_id": "plan-1",
                "starts_on": "2026-08-01",
                "renews_on": None,
                "status": "past_due",
                "payer_contact": "owner@other.example",
            }
        )
        self.db.subs.append({**self.db.subs[0], "id": "sub-1b"})
        self.db.invoices.append(_invoice(id="inv-cur", status="sent", amount_hkd=100.0, due_on=today.isoformat()))
        self.db.invoices.append(_invoice(id="inv-a", number="STD-2026-0002", status="sent", amount_hkd=200.0, due_on=(today - timedelta(days=10)).isoformat()))
        self.db.invoices.append(_invoice(id="inv-b", number="STD-2026-0003", subscription_id="sub-1b", status="overdue", amount_hkd=300.0, due_on=(today - timedelta(days=40)).isoformat()))
        self.db.invoices.append(_invoice(id="inv-c", number="STD-2026-0004", subscription_id="sub-2", status="overdue", amount_hkd=50.0, due_on=(today - timedelta(days=3)).isoformat()))
        aging = board_receivables.op_aging_report(None, {})
        providers = aging["pastDueByProvider"]
        self.assertEqual([p["organizationId"] for p in providers], ["org-1", "org-2"])
        org1 = providers[0]
        self.assertEqual(org1["amountHkd"], 500.0)
        self.assertEqual(org1["oldestDaysOverdue"], 40)
        self.assertEqual(org1["invoiceCount"], 2)
        self.assertEqual(sorted(org1["subscriptionIds"]), ["sub-1", "sub-1b"])
        self.assertEqual(org1["payerContact"], "billing@provider.example")
        self.assertEqual(providers[1]["amountHkd"], 50.0)
        self.assertEqual(providers[1]["oldestDaysOverdue"], 3)
        self.assertEqual(aging["outstandingHkd"], 650.0)
        for bucket in aging["buckets"].values():
            for item in bucket:
                self.assertIn("organization_id", item)

    def test_unit_economics_cpa_and_margin(self) -> None:
        today = date.today()
        month_start = today.replace(day=1)
        self.db.subs[0]["starts_on"] = month_start.isoformat()
        self.db.subs.append({**self.db.subs[0], "id": "sub-new", "starts_on": today.isoformat()})
        self.db.subs.append({**self.db.subs[0], "id": "sub-old", "starts_on": "2026-01-15"})
        self.db.subs.append({**self.db.subs[0], "id": "sub-cancelled", "starts_on": today.isoformat(), "status": "cancelled"})
        self.db.invoices.append(_invoice(id="inv-paid-now", status="paid", amount_hkd=1560.0, issued_on=today.isoformat()))
        self.db.invoices.append(_invoice(id="inv-paid-old", status="paid", number="STD-2026-0002", amount_hkd=5000.0, issued_on="2026-01-20"))
        board_store.put_cache(self.table, "aws:monthly_cost", {"totalUsd": 60.0}, ttl_seconds=3600)
        board_store.record_ads_spend(self.table, daily_usd=10.0, monthly_usd=40.0)
        out = board_receivables.op_unit_economics(self._ctx(), {})
        self.assertEqual(out["newActiveSubscriptions"], 2)
        self.assertEqual(out["awsMonthlyUsd"], 60.0)
        self.assertEqual(out["metaAdsMonthlyUsd"], 40.0)
        # (60 + 40) USD ÷ 2 new subscriptions
        self.assertEqual(out["cpaUsd"], 50.0)
        self.assertEqual(out["revenueMonthHkd"], 1560.0)
        self.assertEqual(out["costMonthHkd"], 780.0)  # 100 USD × 7.8
        self.assertEqual(out["grossMarginPct"], 50.0)
        self.assertEqual(out["usdHkdRate"], board_receivables.USD_HKD)
        self.assertEqual(out["paidInvoicesHkd"], 6560.0)
        self.assertIn("7.8", out["note"])

    def test_unit_economics_nulls_without_subscriptions_or_revenue(self) -> None:
        self.db.subs.clear()
        out = board_receivables.op_unit_economics(self._ctx(), {})
        self.assertEqual(out["newActiveSubscriptions"], 0)
        self.assertIsNone(out["cpaUsd"])
        self.assertIsNone(out["grossMarginPct"])
        self.assertEqual(out["revenueMonthHkd"], 0.0)

    def test_unit_economics_excludes_non_usd_meta_from_cpa(self) -> None:
        self.db.subs[0]["starts_on"] = date.today().isoformat()
        board_store.put_cache(self.table, "aws:monthly_cost", {"totalUsd": 30.0}, ttl_seconds=3600)
        snapshot = {"graphMonthlyUsd": 500.0, "recordedMonthlyUsd": 0.0, "graphCurrency": "HKD", "graphAvailable": True}
        with patch("board_meta.ads_spend_snapshot", return_value=snapshot):
            out = board_receivables.op_unit_economics(self._ctx(), {})
        self.assertEqual(out["metaAdsCurrency"], "HKD")
        self.assertNotIn("metaAdsMonthlyUsd", out)
        self.assertEqual(out["cpaUsd"], 30.0)
        self.assertIn("excluded from cpaUsd", out["note"])


class TestSqlFileAndSmokeCli(unittest.TestCase):
    def test_sql_file_has_role_section_and_pinned_revision(self) -> None:
        text = SQL_FILE.read_text(encoding="utf-8")
        self.assertIn("0029_add_api_keys", text)
        self.assertIn("listing_events_daily", text)
        self.assertRegex(text, r"IF NOT EXISTS \(SELECT 1 FROM pg_roles WHERE rolname = 'board_api'\)")
        self.assertIn("GRANT SELECT ON v_catalog_health, v_funnel_daily, v_provider_pipeline TO board_api;", text)
        self.assertIn("GRANT SELECT ON listing_plans, listing_subscriptions, invoices, payments TO board_api;", text)
        self.assertIn("GRANT INSERT, UPDATE ON invoices, payments, listing_plans TO board_api;", text)
        self.assertIn("GRANT UPDATE (status) ON listing_subscriptions TO board_api;", text)
        # Completeness is computed per activity and then averaged.
        self.assertIn("WITH activity_completeness AS", text)
        self.assertIn("FILTER (WHERE p.venue_rank = 1)", text)
        self.assertNotRegex(text, r"AVG\(\s*\(CASE WHEN COALESCE\(cardinality")
        # Live-schema column names.
        for needle in ("a.org_id", "l.lat IS NOT NULL AND l.lng IS NOT NULL", "ga.name", "cardinality(o.media_urls)", "l.area_id"):
            self.assertIn(needle, text)

    def test_smoke_cli_dry_run_prints_typed_statements_without_aws(self) -> None:
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("smoke_data_api", SMOKE_CLI)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        buf = io.StringIO()
        with patch("boto3.client", side_effect=AssertionError("dry-run must not call AWS")), redirect_stdout(buf):
            code = module.main(["--dry-run"])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("v_catalog_health", text)
        self.assertIn("v_funnel_daily", text)
        self.assertIn("v_provider_pipeline", text)
        self.assertIn("INSERT INTO invoices", text)
        self.assertIn("[in transaction, rolled back]", text)
        for hint in ("UUID", "DATE", "DECIMAL"):
            self.assertIn(f'"typeHint": "{hint}"', text)
        write = module.write_statement()
        self.assertTrue(write.write)
        self.assertEqual({p["name"]: p.get("typeHint") for p in write.parameters if p["name"] in ("id", "issued", "amount")}, {"id": "UUID", "issued": "DATE", "amount": "DECIMAL"})
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf), self.assertRaises(SystemExit):
            module.main([])


if __name__ == "__main__":
    unittest.main()
