"""Follow-ups after T8: meeting writes, phishing, templates, PDF, timeouts."""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import board_budget
import board_data_api
import board_deadline
import board_invoice_pdf
import board_mail
import board_meta
import board_pii
import board_store
import board_tools
from board_tools import REGISTRY, ToolContext, ToolOp, execute_call
from contract_constants import BOARD_KEY
from test_board_mail import MailTestCase, build_mail
from test_board_t5 import MetaTestCase
from test_board_tools import ToolsTestCase


def _slow_op(run, *, timeout_seconds: int) -> ToolOp:
    return ToolOp(
        name="slow_test_op",
        tool_id="board",
        kind="read",
        description="test",
        parameters={"type": "object", "properties": {}},
        run=run,
        summarize=lambda _a: "slow",
        timeout_seconds=timeout_seconds,
    )


class TestMeetingWrites(ToolsTestCase):
    def test_ciso_can_report_phishing_at_mail_read(self) -> None:
        settings = board_store.default_settings()
        names = {op.name for op, _ in board_tools.available_ops(settings, "ciso", context="chat")}
        self.assertIn("mail_report_phishing", names)
        self.assertNotIn("mail_send", names)

    def test_timeout_returns_before_the_op_finishes(self) -> None:
        finished = threading.Event()
        release = threading.Event()  # time.sleep is patched out by BoardTestCase; block on an Event instead

        def run(_ctx, _args):
            release.wait(3)
            finished.set()
            return {"ok": True}

        self.addCleanup(release.set)

        ctx = ToolContext(table=self.table, settings=board_store.default_settings(), persona_id="ceo", display_name="CEO")
        started = time.monotonic()
        with patch.object(board_tools, "BOARD_TOOL_CALL_TIMEOUT_SECONDS", 1):
            out = execute_call(ctx, _slow_op(run, timeout_seconds=1), {})
        elapsed = time.monotonic() - started
        self.assertEqual(out.status, "error")
        self.assertIn("timed out", out.result["error"])
        self.assertLess(elapsed, 2.5, "execute_call must not wait for the worker thread")
        self.assertFalse(finished.is_set())

    def test_http_timeouts_shrink_to_the_op_deadline(self) -> None:
        seen: list[float | None] = []

        def run(_ctx, _args):
            seen.append(board_deadline.remaining(25))
            return {"ok": True}

        ctx = ToolContext(table=self.table, settings=board_store.default_settings(), persona_id="ceo", display_name="CEO")
        out = execute_call(ctx, _slow_op(run, timeout_seconds=2), {})
        self.assertEqual(out.status, "ok")
        self.assertTrue(seen and seen[0] is not None and 0.5 <= seen[0] <= 2.0, seen)
        # Outside an op there is no deadline: clients keep their own timeout.
        self.assertEqual(board_deadline.remaining(25), 25)

    def test_phishing_report_is_always_a_proposal_even_at_act(self) -> None:
        settings = board_store.default_settings()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["mail"]["cfo"] = "act"
        self.assertEqual(board_tools.effective_level(settings, "mail", "cfo"), "act")
        ctx = ToolContext(table=self.table, settings=settings, persona_id="cfo", display_name="CFO")
        with patch.object(board_mail, "op_report_phishing") as run:
            out = execute_call(ctx, REGISTRY["mail_report_phishing"], {"threadId": "t-1", "reason": "Looks fake."})
        self.assertEqual(out.status, "pending_approval")
        run.assert_not_called()


class TestPhishing(MailTestCase):
    def test_report_is_proposal_then_action(self) -> None:
        ingested = board_mail.ingest_bytes(self.table, build_mail(frm="evil@phish.example", subject="Reset now"))
        thread_id = ingested["threadId"]
        ctx = ToolContext(
            table=self.table,
            settings=board_store.default_settings(),
            persona_id="ciso",
            display_name="CISO",
        )
        out = execute_call(
            ctx,
            REGISTRY["mail_report_phishing"],
            {"threadId": thread_id, "note": "Lookalike domain", "reason": "CISO review."},
        )
        self.assertEqual(out.status, "pending_approval")
        owner = ToolContext(
            table=self.table,
            settings=board_store.default_settings(),
            persona_id="ciso",
            display_name="Founder",
            actor="owner",
            owner_sub="owner-1",
        )
        decided = execute_call(
            owner,
            REGISTRY["mail_report_phishing"],
            {"threadId": thread_id, "note": "Lookalike domain", "reason": "Approved."},
        )
        self.assertEqual(decided.status, "ok")
        actions = [a for a in board_store.list_actions(self.table) if "Phishing" in str(a.get("title"))]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["source"], "approval")
        again = execute_call(
            owner,
            REGISTRY["mail_report_phishing"],
            {"threadId": thread_id, "note": "Lookalike domain", "reason": "Approved twice."},
        )
        self.assertEqual(again.status, "ok")
        self.assertTrue(again.result.get("duplicate"))
        self.assertEqual(len([a for a in board_store.list_actions(self.table) if "Phishing" in str(a.get("title"))]), 1)


class TestCommentAliases(MetaTestCase):
    def test_commenter_names_never_reach_the_model(self) -> None:
        original = self.graph.__call__

        def with_names(req, timeout=None):
            resp = original(req, timeout)
            if "/feed" in req.full_url:
                payload = json.loads(resp.read())
                payload["data"][0]["comments"]["data"][0]["from"] = {"id": "u1", "name": "Wendy Chan"}
                payload["data"][0]["comments"]["data"].append({"id": "c2", "from": {"id": "u2", "name": "Ka Ming"}, "message": "Price?"})

                class _R:
                    def read(self) -> bytes:
                        return json.dumps(payload).encode()

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return None

                return _R()
            return resp

        with patch.object(board_meta, "_urlopen", with_names):
            first = board_meta.op_list_comments(self._ctx(), {})
            second = board_meta.op_list_comments(self._ctx(), {})
        dumped = str(first)
        self.assertNotIn("Wendy", dumped)
        self.assertNotIn("Ka Ming", dumped)
        self.assertNotIn('"u1"', dumped)
        froms = [c["from"] for c in first["posts"][0]["comments"]]
        self.assertTrue(all(f.startswith("contact#") for f in froms), froms)
        self.assertEqual(len(set(froms)), 2)
        self.assertEqual(froms, [c["from"] for c in second["posts"][0]["comments"]])
        pseud = board_pii.Pseudonymizer(self.table)
        self.assertEqual(pseud.resolve(froms[0]), "Wendy Chan")

    def test_no_table_falls_back_to_hidden(self) -> None:
        self.assertEqual(board_meta._mask_sender({"id": "u1", "name": "Wendy"}, None), "contact#hidden")
        self.assertEqual(board_meta._mask_sender({}, None), "contact#unknown")


class TestPseudonymizerSave(ToolsTestCase):
    def test_concurrent_writers_merge_instead_of_clobbering(self) -> None:
        a = board_pii.Pseudonymizer(self.table)
        b = board_pii.Pseudonymizer(self.table)
        alias_a = a.alias_for("contact", "parent-a@example.com")
        alias_b = b.alias_for("contact", "parent-b@example.com")
        self.assertEqual(alias_a, alias_b, "both start from an empty map and pick contact#1")
        a.save()
        b.save()
        stored = board_pii.Pseudonymizer(self.table)
        self.assertEqual(stored.resolve(alias_a), "parent-a@example.com")
        self.assertEqual(stored.alias_for("contact", "parent-b@example.com"), "contact#2")
        self.assertFalse(stored._dirty)
        self.assertEqual(stored.state["next"], 3)

    def test_same_value_from_two_writers_keeps_one_digest(self) -> None:
        a = board_pii.Pseudonymizer(self.table)
        b = board_pii.Pseudonymizer(self.table)
        a.alias_for("phone", "+852 9123 4567")
        b.alias_for("phone", "+852 9123 4567")
        a.save()
        b.save()
        stored = board_pii.Pseudonymizer(self.table)
        self.assertEqual(stored.alias_for("phone", "+852 9123 4567"), "phone#1")
        self.assertEqual(len(stored.state["byDigest"]), 1)


class TestTemplates(MetaTestCase):
    def test_lists_approved_templates(self) -> None:
        out = board_meta.op_list_whatsapp_templates(self._ctx(), {})
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["templates"][0]["name"], "hello_world")
        self.assertEqual(out["wabaId"], "waba-1")
        template_calls = [url for _m, url, _b in self.graph.calls if "/message_templates" in url]
        self.assertTrue(all("status=APPROVED" in url for url in template_calls), template_calls)

    def test_waba_lookup_is_cached_and_pages_follow_cursors(self) -> None:
        original = self.graph.__call__
        pages = {"": ["a", "b"], "cur2": ["c"]}

        def paged(req, timeout=None):
            url = req.full_url
            if "/message_templates" not in url:
                return original(req, timeout)
            after = url.split("after=", 1)[1].split("&", 1)[0] if "after=" in url else ""
            self.graph.calls.append((req.get_method(), url, None))
            payload = {
                "data": [{"name": n, "status": "APPROVED", "language": "en", "category": "UTILITY"} for n in pages[after]]
                + ([{"name": "pending_one", "status": "PENDING"}] if not after else []),
            }
            if not after:
                payload["paging"] = {"cursors": {"after": "cur2"}, "next": "https://graph/next"}

            class _R:
                def read(self) -> bytes:
                    return json.dumps(payload).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return None

            return _R()

        with patch.object(board_meta, "_urlopen", paged):
            first = board_meta.op_list_whatsapp_templates(self._ctx(), {})
            second = board_meta.op_list_whatsapp_templates(self._ctx(), {})
        self.assertEqual([t["name"] for t in first["templates"]], ["a", "b", "c"])
        self.assertEqual(first["count"], 3)
        self.assertEqual(second["count"], 3)
        waba_lookups = [url for _m, url, _b in self.graph.calls if "whatsapp_business_account" in url]
        self.assertEqual(len(waba_lookups), 1, "WABA id must be resolved once per warm Lambda")


class TestInvoicePdf(unittest.TestCase):
    def _render(self, payer: str) -> board_invoice_pdf.InvoicePdf:
        return board_invoice_pdf.render_invoice(
            number="STD-2026-0001",
            amount_hkd=388,
            fps_reference="STDABCDEF",
            issued_on="2026-09-04",
            due_on="2026-09-18",
            payer_contact=payer,
        )

    def test_invoice_s3_key_is_tenant_prefixed(self) -> None:
        self.assertEqual(
            board_invoice_pdf.invoice_s3_key("inv-1", "2026-09-01"),
            f"board/{BOARD_KEY}/invoices/2026/inv-1.pdf",
        )

    def test_pdf_bytes_are_valid_header(self) -> None:
        out = self._render("billing@provider.example")
        pdf = out.data
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"STD-2026-0001", pdf)
        self.assertIn(b"STDABCDEF", pdf)
        self.assertIn(b"/Encoding /WinAnsiEncoding", pdf)
        self.assertNotIn(b"?", pdf.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0])
        self.assertEqual(out.notes, ())
        self.assertEqual(board_invoice_pdf.render_invoice_pdf(
            number="STD-2026-0001", amount_hkd=388, fps_reference="STDABCDEF", issued_on="2026-09-04", due_on="2026-09-18"
        )[:8], b"%PDF-1.4")

    def test_non_latin_payer_is_dropped_and_reported(self) -> None:
        out = self._render("陳小美 (Splash Ltd) café")
        stream = out.data.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0]
        self.assertIn(b"Billed to  \\(Splash Ltd\\) cafe", stream)
        self.assertNotIn(b"?", stream)
        self.assertEqual(out.notes, (board_invoice_pdf.NON_LATIN_NOTE,))
        stream.decode("cp1252")

    def test_xref_offsets_match_object_positions(self) -> None:
        pdf = self._render("").data
        xref_at = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
        self.assertTrue(pdf[xref_at:].startswith(b"xref"))
        entries = pdf[xref_at:].split(b"\n")[3:8]
        for i, entry in enumerate(entries, start=1):
            off = int(entry.split()[0])
            self.assertTrue(pdf[off:].startswith(f"{i} 0 obj".encode()), (i, pdf[off : off + 12]))


class TestInvoicePdfStorage(ToolsTestCase):
    def _db(self):
        import board_data_api
        from test_board_t4 import FakeAurora

        db = FakeAurora()
        db.subs.append(
            {
                "id": "sub-1",
                "organization_id": "org-1",
                "store_id": None,
                "plan_id": "plan-1",
                "starts_on": "2026-08-01",
                "renews_on": "2026-10-01",
                "status": "active",
                "payer_contact": "billing@provider.example",
            }
        )
        board_data_api.set_executor_for_tests(db)
        self.addCleanup(lambda: board_data_api.set_executor_for_tests(None))
        return db

    def test_draft_reports_when_s3_upload_fails(self) -> None:
        import board_receivables

        db = self._db()
        with patch("runtime._s3") as s3:
            s3.put_object.side_effect = RuntimeError("AccessDenied")
            out = board_receivables.op_draft_invoice(None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "PDF."})
        self.assertTrue(out["ok"])
        self.assertEqual(out["pdfKey"], "")
        self.assertIn("could not be stored", out["pdfWarning"])
        self.assertIsNone(db.invoices[0].get("pdf_key"))

    def test_send_reports_missing_attachment(self) -> None:
        import board_receivables
        from test_board_mail import FakeSES

        db = self._db()
        db.invoices.append(
            {
                "id": "inv-1",
                "subscription_id": "sub-1",
                "number": "STD-2026-0001",
                "issued_on": "2026-09-01",
                "due_on": "2026-09-15",
                "amount_hkd": 388,
                "status": "draft",
                "fps_reference": "STDREF001",
                "pdf_key": f"board/{BOARD_KEY}/invoices/2026/inv-1.pdf",
            }
        )
        ses = FakeSES()
        env = {"BOARD_MAIL_SENDING_ENABLED": "true", "BOARD_MAIL_DOMAIN": "siutindei.com"}
        settings = board_store.default_settings()
        settings["tools"]["allowList"] = {"emails": ["billing@provider.example"], "phones": []}
        ctx = ToolContext(table=self.table, settings=settings, persona_id="cfo", display_name="CFO", actor="owner", owner_sub="o")
        with patch.dict("os.environ", env), patch.object(board_mail, "_ses_client", lambda: ses), patch("runtime._s3") as s3:
            s3.get_object.side_effect = RuntimeError("NoSuchKey")
            s3.head_object.side_effect = RuntimeError("NoSuchKey")
            preview = board_receivables.owner_preview_send(ctx, {"invoiceId": "inv-1"}, op="finance_send_invoice")
            out = board_receivables.op_send_invoice(ctx, {"invoiceId": "inv-1", "reason": "Send."})
        self.assertEqual(preview["attachments"], [])
        self.assertIn("missing", preview["pdfWarning"])
        self.assertTrue(out["ok"])
        self.assertTrue(out["attachmentMissing"])
        self.assertEqual(len(ses.sent), 1)
        self.assertNotIn("application/pdf", ses.sent[-1]["Content"]["Raw"]["Data"].decode("utf-8", "replace"))


class TestUnitEconomicsMeta(ToolsTestCase):
    def _run(self, *, graph: dict, recorded: float):
        import board_receivables
        from test_board_t4 import FakeAurora

        import board_data_api

        db = FakeAurora()
        board_data_api.set_executor_for_tests(db)
        self.addCleanup(lambda: board_data_api.set_executor_for_tests(None))
        if recorded:
            board_store.record_ads_spend(self.table, daily_usd=recorded, monthly_usd=recorded)
        ctx = ToolContext(table=self.table, settings=board_store.default_settings(), persona_id="cfo", display_name="CFO")
        with patch.object(board_meta, "graph_month_spend_detail", return_value=graph):
            return board_receivables.op_unit_economics(ctx, {})

    def test_graph_actuals_win_over_recorded_commitments(self) -> None:
        out = self._run(graph={"spend": 30.0, "currency": "USD", "available": True}, recorded=4.0)
        self.assertEqual(out["metaAdsMonthlyUsd"], 30.0)
        self.assertEqual(out["metaAdsSource"], "graph")
        self.assertEqual(out["metaAdsRecordedMonthlyUsd"], 4.0)

    def test_recorded_used_when_graph_unavailable(self) -> None:
        out = self._run(graph={"spend": 0.0, "currency": "", "available": False}, recorded=4.0)
        self.assertEqual(out["metaAdsMonthlyUsd"], 4.0)
        self.assertEqual(out["metaAdsSource"], "recorded")

    def test_non_usd_account_is_labelled_not_converted(self) -> None:
        out = self._run(graph={"spend": 250.0, "currency": "HKD", "available": True}, recorded=0.0)
        self.assertNotIn("metaAdsMonthlyUsd", out)
        self.assertEqual(out["metaAdsCurrency"], "HKD")
        self.assertIn("HKD", out["note"])

    def test_unit_economics_is_a_slow_op(self) -> None:
        self.assertEqual(REGISTRY["finance_unit_economics"].timeout_seconds, board_tools.BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS)


class TestGraphErrors(MetaTestCase):
    def test_socket_timeout_while_reading_becomes_meta_error(self) -> None:
        import socket

        class _Stalls:
            def read(self):
                raise socket.timeout("timed out")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

        with patch.object(board_meta, "_urlopen", lambda req, timeout=None: _Stalls()):
            with self.assertRaises(board_meta.MetaError):
                board_meta.graph("GET", "act_99/insights")
            self.assertEqual(board_meta.graph_month_spend_detail()["available"], False)


class TestDraftInvoiceStoresPdf(ToolsTestCase):
    def test_draft_writes_pdf_when_s3_works(self) -> None:
        import board_data_api
        import board_receivables
        from test_board_t4 import FakeAurora

        db = FakeAurora()
        db.subs.append(
            {
                "id": "sub-1",
                "organization_id": "org-1",
                "store_id": None,
                "plan_id": "plan-1",
                "starts_on": "2026-08-01",
                "renews_on": "2026-10-01",
                "status": "active",
                "payer_contact": "billing@provider.example",
            }
        )
        board_data_api.set_executor_for_tests(db)
        self.addCleanup(lambda: board_data_api.set_executor_for_tests(None))
        put = MagicMock()
        with patch("runtime._s3") as s3:
            s3.put_object = put
            out = board_receivables.op_draft_invoice(
                None, {"subscriptionId": "sub-1", "amountHkd": 388, "reason": "PDF."}
            )
        self.assertTrue(out["ok"])
        self.assertTrue(str(out.get("pdfKey") or "").startswith(f"board/{BOARD_KEY}/invoices/"))
        put.assert_called_once()
        self.assertEqual(db.invoices[0]["pdf_key"], out["pdfKey"])


# ---------------------------------------------------------------------------
# WP1: guardrail core
# ---------------------------------------------------------------------------

ALWAYS_PROPOSE_OPS = (
    "github_create_issue",
    "meta_propose_post",
    "meta_propose_story",
    "finance_draft_invoice",
    "finance_propose_price_change",
    "finance_record_manual_payment",
    "mail_report_phishing",
    "security_open_remediation",
    "aws_propose_budget_alert",
)


class TestAlwaysPropose(ToolsTestCase):
    def _act_settings(self, tool_id: str, persona: str) -> dict:
        settings = board_store.default_settings()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"].setdefault(tool_id, {})[persona] = "act"
        return settings

    def test_plan_listed_writes_stay_in_approvals_at_act(self) -> None:
        for name in ALWAYS_PROPOSE_OPS:
            op = REGISTRY[name]
            with self.subTest(op=name):
                self.assertTrue(op.always_propose, f"{name} must be always_propose per plan §5")
                settings = self._act_settings(op.tool_id, "ceo")
                ctx = ToolContext(table=self.table, settings=settings, persona_id="ceo", display_name="CEO")
                args = {k: _sample_value(v) for k, v in op.parameters["properties"].items()}
                with patch.object(board_tools, "_invoke_op") as run:
                    out = execute_call(ctx, op, args)
                self.assertEqual(out.status, "pending_approval", out.result)
                run.assert_not_called()

    def test_act_guarded_writes_still_execute_at_act(self) -> None:
        # github_comment_issue has no always_propose flag: it must run at act.
        op = REGISTRY["github_comment_issue"]
        self.assertFalse(op.always_propose)
        ctx = ToolContext(table=self.table, settings=self._act_settings("github", "cto"), persona_id="cto", display_name="CTO")
        with patch.object(board_tools, "_invoke_op", return_value={"ok": True}) as run:
            out = execute_call(ctx, op, {"number": 1, "body": "hi", "reason": "r"})
        self.assertEqual(out.status, "ok")
        run.assert_called_once()


def _sample_value(spec: dict) -> object:
    kind = spec.get("type")
    if kind == "string":
        return spec["enum"][0] if spec.get("enum") else "x"
    if kind == "integer":
        return int(spec.get("minimum", 1))
    if kind == "number":
        return 10
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    return {}


class TestArgumentValidation(ToolsTestCase):
    def _ctx(self, level: str = "act") -> ToolContext:
        settings = board_store.default_settings()
        settings["tools"]["globalMode"] = level
        settings["tools"]["matrix"]["github"]["cto"] = level
        return ToolContext(table=self.table, settings=settings, persona_id="cto", display_name="CTO")

    def test_unknown_keys_are_rejected_without_a_proposal(self) -> None:
        ctx = self._ctx("propose")
        out = execute_call(ctx, REGISTRY["github_create_issue"], {"title": "t", "body": "b", "reason": "r", "pageId": "123"})
        self.assertEqual(out.status, "error")
        self.assertIn("unknown argument 'pageId'", out.result["error"])
        self.assertEqual([a for a in board_store.list_approvals(self.table)], [])
        row = board_store.list_tool_calls(self.table, limit=1)[0]
        self.assertEqual(row["status"], "error")

    def test_type_enum_length_and_range_checks(self) -> None:
        ctx = self._ctx("act")
        op = REGISTRY["board_add_action"]
        cases = [
            ({"title": "t", "detail": "d", "priority": "urgent", "reason": "r"}, "must be one of"),
            ({"title": "t" * 500, "detail": "d", "priority": "now", "reason": "r"}, "longer than"),
            ({"title": "t", "detail": "d", "priority": "now", "dueInDays": 0, "reason": "r"}, "at least"),
            ({"title": "t", "detail": "d", "priority": "now", "dueInDays": "soon", "reason": "r"}, "must be a number"),
            ({"title": ["t"], "detail": "d", "priority": "now", "reason": "r"}, "must be a string"),
            ({"detail": "d", "priority": "now", "reason": "r"}, "'title' is required"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                out = execute_call(ctx, op, args)
                self.assertEqual(out.status, "error", out.result)
                self.assertIn(expected, out.result["error"])

    def test_numeric_strings_and_decimals_are_coerced(self) -> None:
        from decimal import Decimal

        op = REGISTRY["board_add_action"]
        cleaned = board_tools.validate_arguments(
            op, {"title": "t", "detail": "d", "priority": "now", "dueInDays": "7", "reason": "r", "metric": None}
        )
        self.assertEqual(cleaned["dueInDays"], 7)
        self.assertNotIn("metric", cleaned)
        cleaned = board_tools.validate_arguments(op, {"title": "t", "detail": "d", "priority": "now", "dueInDays": Decimal("7"), "reason": "r"})
        self.assertEqual(cleaned["dueInDays"], 7)

    def test_oversized_arguments_are_an_error_outcome(self) -> None:
        ctx = self._ctx("act")
        out = execute_call(ctx, REGISTRY["github_create_issue"], {"title": "t", "body": "b" * 9000, "reason": "r"})
        self.assertEqual(out.status, "error")
        self.assertIn("too large", out.result["error"])
        self.assertEqual(board_store.list_approvals(self.table), [])

    def test_owner_override_is_validated_and_stays_pending(self) -> None:
        approval = self.propose_issue()
        approval_id = approval["approvalId"]
        status, body = self.call(
            f"/siu-tin-dei/board/approvals/{approval_id}/approve", "POST", {"arguments": {"title": "", "labels": "billing"}}
        )
        self.assertEqual(status, 400)
        self.assertIn("required", body["message"])
        _, listing = self.call("/siu-tin-dei/board/approvals", query="status=pending")
        self.assertEqual([a["approvalId"] for a in listing["approvals"]], [approval_id])
        status, body = self.call(f"/siu-tin-dei/board/approvals/{approval_id}/approve", "POST", {"arguments": {"pageId": "1"}})
        self.assertEqual(status, 400)
        self.assertIn("unknown argument", body["message"])


class TestDecideApprovalGates(ToolsTestCase):
    def test_disabled_or_read_only_refuses_and_keeps_pending(self) -> None:
        approval = self.propose_issue()
        approval_id = approval["approvalId"]
        self.call("/siu-tin-dei/board/tools", "PUT", {"enabled": False})
        status, body = self.call(f"/siu-tin-dei/board/approvals/{approval_id}/approve", "POST", {})
        self.assertEqual(status, 409)
        self.assertIn("switched off", body["message"])
        self.call("/siu-tin-dei/board/tools", "PUT", {"enabled": True, "globalMode": "readOnly"})
        status, body = self.call(f"/siu-tin-dei/board/approvals/{approval_id}/approve", "POST", {})
        self.assertEqual(status, 409)
        self.assertIn("read-only", body["message"])
        self.assertEqual(board_store.get_approval(self.table, approval_id)["status"], "pending")
        # Rejecting is always allowed: nothing executes.
        status, body = self.call(f"/siu-tin-dei/board/approvals/{approval_id}/reject", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["approval"]["status"], "rejected")

    def test_crash_during_execution_marks_failed_not_approved(self) -> None:
        approval = self.propose_issue()
        with patch.object(board_tools, "execute_call", side_effect=RuntimeError("boom")):
            status, body = self.call(f"/siu-tin-dei/board/approvals/{approval['approvalId']}/approve", "POST", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["approval"]["status"], "failed")
        self.assertIn("boom", body["approval"]["errorMessage"])


class TestAuditMasking(ToolsTestCase):
    def test_tool_call_rows_never_store_raw_contacts(self) -> None:
        settings = board_store.default_settings()
        settings["tools"]["globalMode"] = "act"
        settings["tools"]["matrix"]["mail"]["ceo"] = "act"
        ctx = ToolContext(table=self.table, settings=settings, persona_id="ceo", display_name="CEO")
        args = {
            "fromMailbox": "hello",
            "to": ["parent@example.com"],
            "subject": "Hi",
            "body": "Call me on +852 9123 4567 or parent@example.com",
            "reason": "r",
        }
        with patch.object(board_tools, "_invoke_op", return_value={"ok": True}):
            out = execute_call(ctx, REGISTRY["mail_send"], args)
        # Not allow-listed → downgraded to a proposal; the audit row is written either way.
        self.assertEqual(out.status, "pending_approval")
        row = board_store.list_tool_calls(self.table, limit=1)[0]
        text = json.dumps(row)
        self.assertNotIn("parent@example.com", text)
        self.assertNotIn("9123", text)
        self.assertRegex(row["arguments"]["to"][0], r"^contact#\d+$")
        # The owner can still resolve the alias from the shared pseudonymizer map.
        pseud = board_mail.pseudonymizer(self.table)
        self.assertEqual(pseud.resolve(row["arguments"]["to"][0]), "parent@example.com")


# ---------------------------------------------------------------------------
# WP4: runtime limits
# ---------------------------------------------------------------------------

class TestLoopRuntimeLimits(ToolsTestCase):
    def test_budget_is_rechecked_between_rounds(self) -> None:
        # Two tool rounds scripted; the cap trips after the first paid call.
        scripted = self.use_script(
            [
                [("github_search_issues", {"query": "a"})],
                [("github_search_issues", {"query": "b"})],
            ],
            "Answering with what I have.",
        )
        calls = {"n": 0}
        original = board_budget.check_budget

        def tripping(table, settings):
            calls["n"] += 1
            if calls["n"] >= 3:  # 1st: enqueue route; 2nd: before the turn (board_chat); 3rd: before round 2
                raise board_budget.BudgetExceeded("Daily board budget of USD 1.00 is exhausted.")
            return original(table, settings)

        with patch.object(board_budget, "check_budget", tripping):
            job = self.chat("cto")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["message"]["text"], "Answering with what I have.")
        self.assertEqual(len(job["message"]["toolCalls"]), 1)
        # Round 1 (tool), then the final answer with tool_choice=none — no round 2.
        self.assertEqual([r.get("tool_choice") for r in scripted.requests], ["auto", "none"])
        self.assertIn("No more tool calls are possible", scripted.requests[-1]["messages"][-1]["content"])

    def test_model_call_timeouts_shrink_with_the_loop_budget(self) -> None:
        seen: list[float] = []
        inner = self.use_script([[("github_search_issues", {"query": "a"})]], "ok")

        def spy(req, timeout=None):
            seen.append(timeout)
            return inner(req, timeout)

        self.router.openrouter = spy
        clock = {"t": 1000.0}

        def fake_monotonic():
            clock["t"] += 50.0  # every look at the clock costs 50 s
            return clock["t"]

        with patch("board_tools.time.monotonic", fake_monotonic):
            job = self.chat("cto")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(len(seen), 2)
        self.assertLess(seen[0], 90, "round call must be clamped to the remaining loop budget")
        self.assertGreaterEqual(seen[0], board_tools.MODEL_CALL_TIMEOUT_FLOOR_SECONDS)
        self.assertEqual(seen[1], board_tools.FINAL_CALL_TIMEOUT_FLOOR_SECONDS)

    def test_op_timeout_is_clamped_to_the_turn_deadline(self) -> None:
        seen: list[int] = []
        op = _slow_op(lambda _c, _a: {"ok": True}, timeout_seconds=25)
        ctx = ToolContext(table=self.table, settings=board_store.default_settings(), persona_id="ceo", display_name="CEO")
        ctx.deadline = time.monotonic() + 3

        real_pool = board_tools.ThreadPoolExecutor

        class SpyPool(real_pool):
            def submit(self, fn, *args, **kwargs):
                future = super().submit(fn, *args, **kwargs)
                original = future.result

                def result(timeout=None):
                    seen.append(timeout)
                    return original(timeout=timeout)

                future.result = result
                return future

        with patch.object(board_tools, "ThreadPoolExecutor", SpyPool):
            out = execute_call(ctx, op, {})
        self.assertEqual(out.status, "ok")
        self.assertEqual(seen, [3])

    def test_calls_after_the_deadline_are_refused_within_a_round(self) -> None:
        scripted = self.use_script(
            [[("github_search_issues", {"query": "a"}), ("github_search_issues", {"query": "b"})]], "ok"
        )
        clock = {"t": 1000.0}

        def fake_monotonic():
            clock["t"] += 40.0  # the second call of the round lands past the 120 s deadline
            return clock["t"]

        with patch("board_tools.time.monotonic", fake_monotonic):
            job = self.chat("cto")
        self.assertEqual(job["status"], "succeeded")
        tool_msgs = [m for m in scripted.requests[-1]["messages"] if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 2)
        self.assertIn("Time budget", tool_msgs[1]["content"])
        self.assertEqual(len(job["message"]["toolCalls"]), 1)


# ---------------------------------------------------------------------------
# WP8: backend odds and ends
# ---------------------------------------------------------------------------

class TestUpdateActionReprioritise(ToolsTestCase):
    def test_priority_and_due_date_can_change(self) -> None:
        self.call("/siu-tin-dei/board/tools", "PUT", {"globalMode": "act"})
        self.use_script([[("board_add_action", {"title": "Draft pricing tiers", "detail": "d", "priority": "later", "reason": "r"})]], "ok")
        self.chat("cfo")
        action_id = self.call("/siu-tin-dei/board/actions")[1]["actions"][0]["actionId"]
        settings = board_store.load_settings(self.table)
        ctx = ToolContext(table=self.table, settings=settings, persona_id="cfo", display_name="CFO")
        op = REGISTRY["board_update_action"]
        out = execute_call(ctx, op, {"actionId": action_id, "priority": "now", "dueInDays": 3, "reason": "r"})
        self.assertEqual(out.status, "ok", out.result)
        action = board_store.get_action(self.table, action_id)
        self.assertEqual(action["priority"], "now")
        self.assertTrue(action["dueAt"])
        self.assertIn("priority → now", out.summary)
        out = execute_call(ctx, op, {"actionId": action_id, "dueInDays": 0, "reason": "r"})
        self.assertEqual(out.status, "ok")
        self.assertIsNone(board_store.get_action(self.table, action_id)["dueAt"])
        out = execute_call(ctx, op, {"actionId": action_id, "priority": "urgent", "reason": "r"})
        self.assertEqual(out.status, "error")
        self.assertIn("must be one of", out.result["error"])


class TestExternalUsage(ToolsTestCase):
    def test_search_calls_are_counted_and_shown_in_overview(self) -> None:
        from test_board_t2 import FakeBrave

        import board_research

        brave = FakeBrave()
        os.environ["SEARCH_API_KEY"] = "brave-local"
        board_research.reset_key_cache_for_tests()
        self.addCleanup(lambda: os.environ.pop("SEARCH_API_KEY", None))
        self.addCleanup(board_research.reset_key_cache_for_tests)
        ctx = ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cfo")
        with patch("board_research.urlrequest.urlopen", brave):
            board_research.op_search(ctx, {"query": "Tuen Mun swimming"})
            board_research.op_search(ctx, {"query": "Tuen Mun swimming"})  # cache hit: no quota
            board_research.op_search(ctx, {"query": "Sha Tin piano"})
        self.assertEqual(board_store.load_external_usage_day(self.table), {"searchCalls": 2})
        _, overview = self.call("/siu-tin-dei/board")
        self.assertEqual(overview["usageToday"]["external"], {"searchCalls": 2, "metaAdsMonthUsd": 0.0})

    def test_online_fallback_is_billed_to_the_daily_budget(self) -> None:
        import board_research

        os.environ.pop("SEARCH_API_KEY", None)
        board_research.reset_key_cache_for_tests()
        ctx = ToolContext(table=self.table, settings=board_store.load_settings(self.table), persona_id="cfo")
        completion = MagicMock(text='[{"title": "T", "url": "https://x.example", "snippet": "s"}]')
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "k"}), patch.object(
            board_budget, "board_completion", return_value=completion
        ) as bc:
            out = board_research.op_search(ctx, {"query": "Tuen Mun swimming"})
        self.assertEqual(out["source"], "openrouter_online")
        self.assertEqual(bc.call_args.kwargs["table"], self.table)
        self.assertEqual(bc.call_args.kwargs["model"], "openrouter/auto:online")
        self.assertEqual(board_store.load_external_usage_day(self.table)["searchCalls"], 1)


class TestProductViewCache(unittest.TestCase):
    def test_unfiltered_reads_are_cached_and_filtered_ones_are_not(self) -> None:
        import board_product
        from test_board import FakeTable
        from test_board_t4 import FakeAurora

        db = FakeAurora()
        board_data_api.set_executor_for_tests(db)
        self.addCleanup(lambda: board_data_api.set_executor_for_tests(None))
        table = FakeTable()
        ctx = ToolContext(table=table, settings=board_store.default_settings(), persona_id="cpo")
        first = board_product.op_catalog_health(ctx, {})
        second = board_product.op_catalog_health(ctx, {})
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(len([s for s in db.sqls if "v_catalog_health" in s]), 1)
        board_product.op_catalog_health(ctx, {"district": "Tuen Mun"})
        self.assertEqual(len([s for s in db.sqls if "v_catalog_health" in s]), 2)
        notes = board_product.refresh_caches(table)
        self.assertEqual(set(notes.values()), {"ok"})


if __name__ == "__main__":
    unittest.main()
