"""Resume store, HTTP API, and the extract and tailor workers."""

from __future__ import annotations

import base64
import io
import json
import unittest
from unittest.mock import patch

from docx import Document
from openrouter_client import ChatCompletion
from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import resume  # noqa: E402
import resume_extract  # noqa: E402
import resume_store  # noqa: E402
import resume_tracker  # noqa: E402
import runtime  # noqa: E402
from dispatch import lambda_handler  # noqa: E402
from resume_store import ResumeError  # noqa: E402

ENABLED = {
    "RECORDS_TABLE_NAME": "records-test",
    "AUDIT_LOG_TABLE_NAME": "audit-test",
    "RESUME_ENABLED": "true",
    "OPENROUTER_MODEL": "openai/gpt-test",
}
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx(*paragraphs: str) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _event(path: str, method: str = "GET", body: dict | None = None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "requestId": "req-resume",
            "authorizer": {"jwt": {"claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}}},
        },
        "rawQueryString": "",
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


def _completion(payload: dict, *, finish_reason: str = "stop", cost: float = 0.02) -> ChatCompletion:
    return ChatCompletion(
        text=json.dumps(payload),
        model="openai/gpt-test",
        usage={"cost": cost},
        finish_reason=finish_reason,
    )


class ResumeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()
        resume_store.clear_memory()

    def test_only_a_ready_docx_can_be_the_template(self) -> None:
        doc = resume_store.create_resume(
            self.table,
            title="Alex Example",
            content_type=DOCX,
            data=_docx("Alex Example", "Built the billing export."),
            make_template=False,
        )
        with self.assertRaises(ResumeError) as caught:
            resume_store.set_template(self.table, doc["resumeId"])
        self.assertEqual(caught.exception.status, 409)
        doc["extract"] = {"status": "ready", "error": ""}
        resume_store.save_resume(self.table, doc)
        self.assertEqual(resume_store.set_template(self.table, doc["resumeId"]), doc["resumeId"])
        self.assertEqual(resume_store.get_resume(self.table, doc["resumeId"])["kind"], "template")

    def test_template_and_referenced_resumes_cannot_be_deleted(self) -> None:
        doc = resume_store.create_resume(
            self.table,
            title="Alex Example",
            content_type=DOCX,
            data=_docx("Alex Example"),
            make_template=False,
        )
        doc["extract"] = {"status": "ready", "error": ""}
        resume_store.save_resume(self.table, doc)
        resume_store.set_template(self.table, doc["resumeId"])
        with self.assertRaises(ResumeError) as caught:
            resume_store.delete_resume(self.table, doc["resumeId"])
        self.assertEqual(caught.exception.status, 409)
        other = resume_store.create_resume(
            self.table,
            title="Archive",
            content_type="text/markdown",
            data=b"# Alex Example\n",
            make_template=False,
        )
        resume_tracker.create_application(
            self.table,
            {"company": "Northwind", "position": "Engineer", "resumeId": other["resumeId"]},
        )
        with self.assertRaises(ResumeError) as referenced:
            resume_store.delete_resume(self.table, other["resumeId"])
        self.assertEqual(referenced.exception.status, 409)

    def test_spend_reserves_then_adjusts_to_the_actual_cost(self) -> None:
        self.assertTrue(resume_store.try_reserve_spend(self.table, 0.05, 5))
        self.assertAlmostEqual(resume_store.month_spend(self.table), 0.05)
        self.assertFalse(resume_store.try_reserve_spend(self.table, 0.05, 0.05))
        self.assertAlmostEqual(resume_store.adjust_spend(self.table, 0.02 - 0.05), 0.02)


class ResumeHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()
        resume_store.clear_memory()
        patcher = patch.object(runtime, "_ddb")
        mock_ddb = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ddb.Table.return_value = self.table
        self.env = patch.dict("os.environ", ENABLED, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_reads_work_and_writes_fail_when_resume_is_off(self) -> None:
        with patch.dict("os.environ", {"RESUME_ENABLED": "false"}):
            overview = lambda_handler(_event("/lx-software/resume/overview"), None)
            self.assertEqual(overview["statusCode"], 200)
            self.assertFalse(_body(overview)["enabled"])
            created = lambda_handler(
                _event(
                    "/lx-software/resume/resumes",
                    "POST",
                    {"title": "Alex Example", "contentType": DOCX, "dataBase64": base64.b64encode(_docx("A")).decode()},
                ),
                None,
            )
            self.assertEqual(created["statusCode"], 403)
            self.assertEqual(_body(created)["reason"], "resume_disabled")

    def test_upload_queues_extract_and_lists_without_paragraphs(self) -> None:
        with patch("board_async.try_invoke_event", return_value=True) as queued:
            uploaded = lambda_handler(
                _event(
                    "/lx-software/resume/resumes",
                    "POST",
                    {
                        "title": "Alex Example",
                        "contentType": DOCX,
                        "dataBase64": base64.b64encode(_docx("Alex Example")).decode(),
                        "makeTemplate": True,
                    },
                ),
                None,
            )
        self.assertEqual(uploaded["statusCode"], 202)
        body = _body(uploaded)
        self.assertEqual(body["job"]["status"], "queued")
        self.assertNotIn("paragraphs", body["resume"])
        queued.assert_called_once()
        self.assertEqual(queued.call_args.args[0]["internal"], "resume_extract")
        listed = lambda_handler(_event("/lx-software/resume/resumes"), None)
        self.assertEqual(_body(listed)["items"][0]["id"], body["resume"]["id"])

    def test_settings_reject_an_unknown_page_size(self) -> None:
        saved = lambda_handler(
            _event("/lx-software/resume/settings", "PUT", {**resume_store.default_settings(), "pageSize": "A3"}),
            None,
        )
        self.assertEqual(saved["statusCode"], 400)
        ok = lambda_handler(
            _event(
                "/lx-software/resume/settings",
                "PUT",
                {**resume_store.default_settings(), "model": "openai/gpt-4.1-mini", "pageSize": "Letter"},
            ),
            None,
        )
        self.assertEqual(ok["statusCode"], 200)
        self.assertEqual(_body(ok)["settings"]["model"], "openai/gpt-4.1-mini")

    def test_records_scan_excludes_resume_rows(self) -> None:
        self.table.put_item(Item={"pk": "RECORD#1", "sk": "A"})
        self.table.put_item(Item={"pk": "RESUME#resume#1", "sk": "RESUME", "title": "hidden"})
        (status,) = (lambda_handler(_event("/records"), None),)
        self.assertEqual(status["statusCode"], 200)
        self.assertEqual(self.table.scan_calls[-1]["ExpressionAttributeValues"][":resume"], "RESUME#")
        self.assertIn("NOT begins_with(pk, :resume)", self.table.scan_calls[-1]["FilterExpression"])

    def test_application_patch_stores_the_recruiter(self) -> None:
        created = lambda_handler(
            _event(
                "/lx-software/resume/applications",
                "POST",
                {"company": "Northwind", "position": "Engineer", "status": "saved"},
            ),
            None,
        )
        application_id = _body(created)["item"]["id"]
        patched = lambda_handler(
            _event(
                f"/lx-software/resume/applications/{application_id}",
                "PATCH",
                {
                    "recruiter": {
                        "name": "Morgan Example",
                        "email": "morgan.example@example.com",
                        "phone": "+852 0000 0000",
                    }
                },
            ),
            None,
        )
        self.assertEqual(patched["statusCode"], 200)
        recruiter = _body(patched)["item"]["recruiter"]
        self.assertEqual(recruiter["email"], "morgan.example@example.com")


class ResumeWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()
        resume_store.clear_memory()
        patcher = patch.object(runtime, "_ddb")
        mock_ddb = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ddb.Table.return_value = self.table
        self.env = patch.dict("os.environ", ENABLED, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_extract_marks_a_docx_ready_and_sets_the_template(self) -> None:
        doc = resume_store.create_resume(
            self.table,
            title="Alex Example",
            content_type=DOCX,
            data=_docx("Alex Example", "alex.example@example.com", "Built the billing export."),
            make_template=True,
        )
        completion = _completion({"paragraphs": [{"id": "p0", "role": "name"}], "roles": []})
        with patch("openrouter_client.chat_completion", return_value=completion) as chat:
            with patch("openrouter_usage.add_usage_day") as usage:
                resume_extract.run(self.table, doc["resumeId"])
        chat.assert_called_once()
        self.assertEqual(chat.call_args.kwargs["service"], "resume")
        self.assertEqual(chat.call_args.kwargs["owner"], "extract")
        self.assertEqual(chat.call_args.kwargs["temperature"], 0)
        usage.assert_called_once()
        self.assertEqual(usage.call_args.kwargs["service"], "resume")
        stored = resume_store.get_resume(self.table, doc["resumeId"])
        self.assertEqual(stored["extract"]["status"], "ready")
        self.assertEqual(resume_store.template_id(self.table), doc["resumeId"])
        self.assertEqual(stored["kind"], "template")

    def test_markdown_extract_does_not_call_the_model(self) -> None:
        doc = resume_store.create_resume(
            self.table,
            title="Alex Example",
            content_type="text/markdown",
            data=b"# Alex Example\n\nBuilt the billing export.\n",
            make_template=False,
        )
        with patch("openrouter_client.chat_completion", side_effect=AssertionError("no model")):
            resume_extract.run(self.table, doc["resumeId"])
        stored = resume_store.get_resume(self.table, doc["resumeId"])
        self.assertEqual(stored["extract"]["status"], "ready")
        self.assertEqual(stored["paragraphs"][0]["text"], "Alex Example")

    def test_extract_failure_is_stored_on_the_resume_and_the_job(self) -> None:
        doc = resume_store.create_resume(
            self.table,
            title="Alex Example",
            content_type=DOCX,
            data=_docx("Alex Example"),
            make_template=False,
        )
        job = resume_store.new_job(self.table, "extract", {"resumeId": doc["resumeId"]})
        with patch("openrouter_client.chat_completion", side_effect=ResumeError("No model is configured.")):
            result = resume.handle_extract({"jobId": job["jobId"], "internal": "resume_extract"})
        self.assertFalse(result["ok"])
        self.assertEqual(resume_store.get_resume(self.table, doc["resumeId"])["extract"]["status"], "failed")
        self.assertEqual(resume_store.get_job(self.table, job["jobId"])["status"], "failed")

    def test_worker_stops_when_resume_is_turned_off(self) -> None:
        doc = resume_store.create_resume(
            self.table,
            title="Alex Example",
            content_type=DOCX,
            data=_docx("Alex Example"),
            make_template=False,
        )
        job = resume_store.new_job(self.table, "extract", {"resumeId": doc["resumeId"]})
        with patch.dict("os.environ", {"RESUME_ENABLED": "false"}):
            result = resume.handle_extract({"jobId": job["jobId"]})
        self.assertFalse(result["ok"])
        self.assertIn("turned off", resume_store.get_job(self.table, job["jobId"])["error"])

    def test_tailor_saves_a_docx_and_a_tracker_row(self) -> None:
        source = _docx("Alex Example", "Engineer", "Built the billing export for Northwind.", "Python, TypeScript")
        doc = resume_store.create_resume(
            self.table, title="Alex Example", content_type=DOCX, data=source, make_template=False
        )
        import resume_docx

        paragraphs = resume_docx.paragraph_map(source)
        doc["paragraphs"] = paragraphs
        doc["layout"] = {
            "paragraphs": [
                {"id": "p0", "role": "name"},
                {"id": "p1", "role": "headline"},
                {"id": "p2", "role": "summary"},
                {"id": "p3", "role": "skills"},
            ],
            "roles": [],
            "overrides": {},
        }
        doc["extract"] = {"status": "ready", "error": ""}
        resume_store.save_resume(self.table, doc)
        resume_store.set_template(self.table, doc["resumeId"])
        posting = resume_tracker.create_posting(
            self.table,
            {
                "title": "Engineer",
                "company": "Northwind",
                "adText": "Northwind needs an engineer who already built a billing export.",
            },
        )
        posting["analysis"] = {"mustHaves": ["billing export"], "keywords": ["Northwind"]}
        resume_tracker.save_posting(self.table, posting)
        job = resume_store.new_job(
            self.table,
            "tailor",
            {"templateId": doc["resumeId"], "postingId": posting["postingId"], "addToTracker": True},
        )
        replacement = _completion(
            {
                "replacements": [
                    {"id": "p1", "text": "Engineer"},
                    {"id": "p2", "text": "Built the billing export for Northwind."},
                ],
                "skills": [{"id": "p3", "text": "Python, TypeScript"}],
            }
        )
        with patch("openrouter_client.chat_completion", return_value=replacement) as chat:
            with patch("openrouter_usage.add_usage_day"):
                result = resume.handle_tailor({"jobId": job["jobId"]})
        self.assertTrue(result["ok"])
        chat.assert_called_once()
        self.assertEqual(chat.call_args.kwargs["max_tokens"], 6000)
        self.assertFalse(chat.call_args.kwargs["reasoning"]["enabled"])
        finished = resume_store.get_job(self.table, job["jobId"])
        self.assertEqual(finished["status"], "done")
        tailored_id = finished["resumeIds"][0]
        tailored = resume_store.get_resume(self.table, tailored_id)
        self.assertEqual(tailored["kind"], "tailored")
        self.assertEqual(tailored["format"], "docx")
        self.assertEqual(resume_store.template_id(self.table), doc["resumeId"])
        applications = resume_tracker.list_applications(self.table)
        self.assertEqual(applications[0]["resumeId"], tailored_id)
        self.assertEqual(applications[0]["status"], "saved")
        self.assertEqual(applications[0]["company"], "Northwind")
        self.assertAlmostEqual(resume_store.month_spend(self.table), 0.02)

    def test_a_failed_tailor_releases_the_reservation_and_saves_nothing(self) -> None:
        source = _docx("Alex Example", "Engineer")
        doc = resume_store.create_resume(
            self.table, title="Alex Example", content_type=DOCX, data=source, make_template=False
        )
        import resume_docx

        doc["paragraphs"] = resume_docx.paragraph_map(source)
        doc["layout"] = {
            "paragraphs": [{"id": "p0", "role": "name"}, {"id": "p1", "role": "headline"}],
            "roles": [],
            "overrides": {},
        }
        doc["extract"] = {"status": "ready", "error": ""}
        resume_store.save_resume(self.table, doc)
        posting = resume_tracker.create_posting(
            self.table, {"title": "Engineer", "company": "Northwind", "adText": "An engineer role at Northwind."}
        )
        posting["analysis"] = {"mustHaves": []}
        resume_tracker.save_posting(self.table, posting)
        job = resume_store.new_job(
            self.table,
            "tailor",
            {"templateId": doc["resumeId"], "postingId": posting["postingId"], "addToTracker": True},
        )
        bad = _completion({"replacements": [{"id": "p1", "text": "Engineer who will unlock 12 new markets"}]})
        with patch("openrouter_client.chat_completion", return_value=bad):
            with patch("openrouter_usage.add_usage_day"):
                result = resume.handle_tailor({"jobId": job["jobId"]})
        self.assertFalse(result["ok"])
        self.assertEqual(resume_store.list_resumes(self.table), [resume_store.get_resume(self.table, doc["resumeId"])])
        self.assertEqual(resume_tracker.list_applications(self.table), [])
        self.assertAlmostEqual(resume_store.month_spend(self.table), 0.0)
        self.assertTrue(resume_store.get_job(self.table, job["jobId"])["findings"])

    def test_length_finish_retries_once_with_double_the_tokens(self) -> None:
        calls: list[int] = []

        def chat(**kwargs: object) -> ChatCompletion:
            calls.append(int(kwargs["max_tokens"]))  # type: ignore[arg-type]
            if len(calls) == 1:
                return _completion({}, finish_reason="length")
            return _completion(
                {"replacements": [{"id": "p1", "text": "Engineer"}], "skills": [{"id": "p2", "text": "Python"}]}
            )

        source = _docx("Alex Example", "Engineer", "Python")
        doc = resume_store.create_resume(
            self.table, title="Alex Example", content_type=DOCX, data=source, make_template=False
        )
        import resume_docx

        doc["paragraphs"] = resume_docx.paragraph_map(source)
        doc["layout"] = {
            "paragraphs": [
                {"id": "p0", "role": "name"},
                {"id": "p1", "role": "headline"},
                {"id": "p2", "role": "skills"},
            ],
            "roles": [],
            "overrides": {},
        }
        doc["extract"] = {"status": "ready", "error": ""}
        resume_store.save_resume(self.table, doc)
        posting = resume_tracker.create_posting(
            self.table, {"title": "Engineer", "company": "Northwind", "adText": "Engineer."}
        )
        posting["analysis"] = {"mustHaves": []}
        resume_tracker.save_posting(self.table, posting)
        job = resume_store.new_job(
            self.table,
            "tailor",
            {"templateId": doc["resumeId"], "postingId": posting["postingId"], "addToTracker": False},
        )
        with patch("openrouter_client.chat_completion", side_effect=chat):
            with patch("openrouter_usage.add_usage_day"):
                result = resume.handle_tailor({"jobId": job["jobId"]})
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [6000, 12000])
