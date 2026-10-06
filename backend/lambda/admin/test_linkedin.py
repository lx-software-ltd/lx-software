"""LinkedIn draft queue: slots, guardrails, and the assisted workflow."""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from test_support import FakeTable, install_aws_stubs

install_aws_stubs()

import linkedin  # noqa: E402
import linkedin_api  # noqa: E402
import linkedin_draft  # noqa: E402
import linkedin_image  # noqa: E402
import linkedin_seeds  # noqa: E402
import linkedin_store  # noqa: E402
import runtime  # noqa: E402
from dispatch import lambda_handler  # noqa: E402
from linkedin_store import HKT, LinkedInError  # noqa: E402
from timeutil import format_iso_millis  # noqa: E402


def _recent_slot(minutes: int = 20) -> str:
    return format_iso_millis(datetime.now(HKT) - timedelta(minutes=minutes))

ENABLED = {
    "RECORDS_TABLE_NAME": "records-test",
    "AUDIT_LOG_TABLE_NAME": "audit-test",
    "LINKEDIN_ENABLED": "true",
    "LINKEDIN_PUBLISH_ENABLED": "false",
    "ADMIN_WEB_ORIGIN": "https://admin.example.com",
    "INBOUND_MAIL_DOMAIN": "inbound.example.com",
}


def _event(path: str, method: str = "GET", body: dict | None = None) -> dict:
    event: dict = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "requestId": "req-linkedin",
            "authorizer": {"jwt": {"claims": {"sub": "admin-sub", "cognito:groups": "[admin]"}}},
        },
        "rawQueryString": "",
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _body(response: dict) -> dict:
    return json.loads(response["body"])


class LinkedInStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()

    def test_default_slot_is_eight_thirty_hkt_on_tuesday_and_thursday(self) -> None:
        now = datetime(2026, 10, 5, 10, 0, tzinfo=HKT)
        slots = linkedin_store.next_slots(linkedin_store.default_settings(), now=now, count=2)
        self.assertEqual(slots[0], "2026-10-06T00:30:00.000Z")
        self.assertEqual(slots[1], "2026-10-08T00:30:00.000Z")

    def test_a_passed_tuesday_slot_moves_to_thursday(self) -> None:
        now = datetime(2026, 10, 6, 9, 0, tzinfo=HKT)
        slots = linkedin_store.next_slots(linkedin_store.default_settings(), now=now, count=1)
        self.assertEqual(slots[0], "2026-10-08T00:30:00.000Z")

    def test_guardrails_block_company_product_and_a_long_hook(self) -> None:
        settings = linkedin_store.default_settings()
        findings = linkedin_store.guardrails(
            "I built this at LX Software and it ships today.",
            "",
            [],
            settings,
        )
        self.assertTrue(any(row["code"] == "forbidden_word" for row in findings))
        product = linkedin_store.guardrails("We mirrored siutindei invoices.", "", [], settings)
        self.assertTrue(any(row["code"] == "product_mention" for row in product))
        long_hook = "x" * 211
        hook = linkedin_store.guardrails(long_hook, "", [], settings)
        self.assertTrue(any(row["code"] == "hook" for row in hook))
        self.assertIn("lx software", linkedin_store.BUILTIN_FORBIDDEN)
        long_commentary = linkedin_store.guardrails("(" * 2000, "", [], settings)
        self.assertTrue(any("LinkedIn allows" in row["detail"] for row in long_commentary))

    def test_owner_forbidden_word_is_settings_not_a_builtin(self) -> None:
        settings = linkedin_store.default_settings()
        settings["forbiddenWords"] = ["acme corp"]
        findings = linkedin_store.guardrails("A note about Acme Corp.", "", [], settings)
        self.assertTrue(any("acme corp" in row["detail"] for row in findings))

    def test_approve_assigns_a_slot_and_an_edit_clears_it(self) -> None:
        settings = linkedin_store.default_settings()
        doc = linkedin_store.create_post(
            self.table,
            {"body": "A short hook.\n\nOne lesson.", "pillar": "architecture"},
            settings=settings,
        )
        approved = linkedin_store.approve_post(
            self.table,
            doc["postId"],
            "admin-sub",
            now=datetime(2026, 10, 5, 10, 0, tzinfo=HKT),
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["slotAt"], "2026-10-06T00:30:00.000Z")
        edited = linkedin_store.update_post(
            self.table,
            doc["postId"],
            {"body": "A different hook.\n\nStill one lesson."},
        )
        self.assertEqual(edited["status"], "drafted")
        self.assertEqual(edited["slotAt"], "")

    def test_approve_refuses_a_failing_post(self) -> None:
        doc = linkedin_store.create_post(
            self.table,
            {"body": "Available immediately for a chat about systems."},
        )
        with self.assertRaises(LinkedInError):
            linkedin_store.approve_post(self.table, doc["postId"], "admin-sub")

    def test_mark_posted_requires_a_linkedin_url(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nDone."})
        with self.assertRaises(LinkedInError):
            linkedin_store.mark_posted(self.table, doc["postId"], "https://example.com/post")
        posted = linkedin_store.mark_posted(
            self.table,
            doc["postId"],
            "https://www.linkedin.com/feed/update/urn:li:share:1",
        )
        self.assertEqual(posted["status"], "published")

    def test_duplicate_body_is_rejected(self) -> None:
        linkedin_store.create_post(self.table, {"body": "Same hook.\n\nSame lesson."})
        with self.assertRaises(LinkedInError):
            linkedin_store.create_post(self.table, {"body": "Same   hook.\n\nSame lesson."})

    def test_weekly_budget_stops_generation(self) -> None:
        settings = linkedin_store.default_settings()
        settings["maxUsdPerMonth"] = 0
        linkedin_store.save_settings(self.table, settings)

        def complete(_messages):
            return {"body": "A short hook.\n\nLesson.", "firstComment": "", "hashtags": [], "pillar": "architecture"}, 0.2

        with self.assertRaises(LinkedInError):
            linkedin_draft.generate_drafts(self.table, count=1, complete=complete)

    def test_generation_stores_a_draft_and_spends(self) -> None:
        calls = {"n": 0}

        def complete(_messages):
            calls["n"] += 1
            return {
                "body": "The hook fits.\n\nThen the lesson, without a pitch.",
                "firstComment": "",
                "hashtags": ["Architecture"],
                "pillar": "architecture",
            }, 0.02

        result = linkedin_draft.generate_drafts(self.table, count=1, pillar="leadership", complete=complete)
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["posts"][0]["pillar"], "leadership")
        self.assertEqual(calls["n"], 1)
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.02)

    def test_failing_draft_gets_one_rewrite(self) -> None:
        calls = {"n": 0}

        def complete(_messages):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"body": "LX Software taught me this.", "firstComment": "", "hashtags": [], "pillar": "delivery"}, 0.01
            return {"body": "A rewrite hook.\n\nThe lesson stands alone.", "firstComment": "", "hashtags": [], "pillar": "delivery"}, 0.01

        result = linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        self.assertEqual(calls["n"], 2)
        self.assertIn("rewrite hook", result["posts"][0]["body"])
        self.assertNotIn("LX Software", result["posts"][0]["body"])

    def test_phrase_boundaries_ignore_longer_words(self) -> None:
        settings = linkedin_store.default_settings()
        allowed = linkedin_store.guardrails(
            "I hire mentors, and the word interimistic is not a status.",
            "",
            [],
            settings,
        )
        self.assertFalse(any(row["code"] == "forbidden_word" for row in allowed))
        blocked = linkedin_store.guardrails("Please hire me. I am interim.", "", [], settings)
        details = " ".join(row["detail"] for row in blocked)
        self.assertIn("hire me", details)
        self.assertIn("interim", details)
        product = linkedin_store.guardrails("A siutindeiish note.", "", [], settings)
        self.assertFalse(any(row["code"] == "product_mention" for row in product))

    def test_phone_and_hashtag_checks_skip_plain_numbers(self) -> None:
        settings = linkedin_store.default_settings()
        plain = linkedin_store.guardrails("We served 10000000 requests. See issue #42.", "", [], settings)
        self.assertFalse(any(row["code"] in ("phone", "hashtags") for row in plain))
        plus = linkedin_store.guardrails("Call +85212345678.", "", [], settings)
        spaced = linkedin_store.guardrails("Call 852 1234 5678.", "", [], settings)
        self.assertTrue(any(row["code"] == "phone" for row in plus))
        self.assertTrue(any(row["code"] == "phone" for row in spaced))
        tight = {**settings, "hashtagCap": 0}
        tagged = linkedin_store.guardrails("See #Architecture.", "", [], tight)
        self.assertTrue(any(row["code"] == "hashtags" for row in tagged))

    def test_slot_with_an_offset_is_stored_as_utc(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nKeep the slot."})
        linkedin_store.approve_post(
            self.table,
            doc["postId"],
            "admin-sub",
            now=datetime(2026, 10, 5, 10, 0, tzinfo=HKT),
        )
        edited = linkedin_store.update_post(
            self.table,
            doc["postId"],
            {"slotAt": "2026-10-06T08:30:00+08:00"},
        )
        self.assertEqual(edited["status"], "approved")
        self.assertEqual(edited["slotAt"], "2026-10-06T00:30:00.000Z")

    def test_settings_save_keeps_spend_and_plan_date(self) -> None:
        linkedin_store.add_spend(self.table, 1.25)
        linkedin_store.save_plan_date(self.table, "2026-10-04")
        saved = linkedin_store.save_settings(self.table, {**linkedin_store.default_settings(), "voiceNotes": ""})
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 1.25)
        self.assertEqual(linkedin_store.load_plan_date(self.table), "2026-10-04")
        self.assertEqual(saved["voiceNotes"], "")
        self.assertEqual(linkedin_store.load_settings(self.table)["voiceNotes"], "")

    def test_retired_default_voice_loads_as_the_recommended_voice(self) -> None:
        linkedin_store.save_settings(
            self.table,
            {
                **linkedin_store.default_settings(),
                "voiceNotes": (
                    "Senior architect writing in the first person. One lesson per post. "
                    "No company name, no employer, no offer of availability."
                ),
            },
        )
        self.assertEqual(
            linkedin_store.load_settings(self.table)["voiceNotes"],
            linkedin_store.RECOMMENDED_VOICE,
        )
        self.assertLessEqual(len(linkedin_store.RECOMMENDED_VOICE), 1000)
        self.assertEqual(linkedin_store.default_settings()["voiceNotes"], linkedin_store.RECOMMENDED_VOICE)
        overview = linkedin_store.overview(self.table)
        self.assertEqual(overview["recommendedVoice"], linkedin_store.RECOMMENDED_VOICE)
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "voiceNotes": "Short sentences. Dry. No emoji."},
        )
        self.assertEqual(
            linkedin_store.load_settings(self.table)["voiceNotes"],
            "Short sentences. Dry. No emoji.",
        )

    def test_settings_save_keeps_openrouter_model(self) -> None:
        saved = linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "model": "openai/gpt-4.1-mini"},
        )
        self.assertEqual(saved["model"], "openai/gpt-4.1-mini")
        self.assertEqual(linkedin_store.load_settings(self.table)["model"], "openai/gpt-4.1-mini")
        with self.assertRaises(LinkedInError):
            linkedin_store.save_settings(self.table, {**saved, "model": "not a slug"})
        with self.assertRaises(LinkedInError):
            linkedin_store.save_settings(self.table, {**saved, "model": "x" * 121})

    def test_regenerate_reuses_a_used_idea(self) -> None:
        idea = linkedin_store.create_idea(self.table, "A used lesson about reviews.", "leadership")
        linkedin_store.mark_idea_used(self.table, idea["ideaId"], "li_old")
        chosen = linkedin_draft.choose_topics(
            self.table,
            linkedin_store.default_settings(),
            count=1,
            idea_ids=[idea["ideaId"]],
        )
        self.assertEqual(chosen[0]["idea"]["text"], "A used lesson about reviews.")
        fresh = linkedin_draft.choose_topics(self.table, linkedin_store.default_settings(), count=1)
        self.assertIn(fresh[0]["idea"]["seedId"], linkedin_seeds.seed_ids())
        self.assertNotIn("ideaId", fresh[0]["idea"])

    def test_seeds_fill_in_when_ideas_run_out_and_rotate(self) -> None:
        settings = linkedin_store.default_settings()
        topics = linkedin_draft.choose_topics(self.table, settings, count=4)
        seed_ids = [row["idea"]["seedId"] for row in topics]
        self.assertEqual(len(set(seed_ids)), 4)
        for row in topics:
            self.assertEqual(row["pillar"], next(s["pillar"] for s in linkedin_seeds.SEEDS if s["id"] == row["idea"]["seedId"]))
        pinned = linkedin_draft.choose_topics(self.table, settings, count=2, pillar="platforms")
        self.assertTrue(all(row["pillar"] == "platforms" for row in pinned))
        self.assertTrue(
            all(next(s["pillar"] for s in linkedin_seeds.SEEDS if s["id"] == row["idea"]["seedId"]) == "platforms" for row in pinned)
        )

    def test_a_used_seed_is_not_picked_again_while_others_remain(self) -> None:
        first = linkedin_draft.choose_topics(self.table, linkedin_store.default_settings(), count=1)[0]
        linkedin_store.create_post(
            self.table,
            {"body": "A short hook.\n\nOne lesson.", "seedId": first["idea"]["seedId"]},
        )
        stored = linkedin_store.list_posts(self.table)[0]
        self.assertEqual(stored["seedId"], first["idea"]["seedId"])
        self.assertEqual(linkedin_store.public_post(stored)["seedId"], first["idea"]["seedId"])
        again = linkedin_draft.choose_topics(self.table, linkedin_store.default_settings(), count=1)[0]
        self.assertNotEqual(again["idea"]["seedId"], first["idea"]["seedId"])

    def test_seed_text_passes_the_stored_guardrails(self) -> None:
        settings = linkedin_store.default_settings()
        for seed in linkedin_seeds.SEEDS:
            self.assertIn(seed["pillar"], linkedin_store.pillar_ids(), seed["id"])
            findings = linkedin_store.guardrails(seed["text"], "", [], settings)
            codes = {row["code"] for row in findings if row["severity"] == "error"}
            self.assertFalse(codes - {"hook"}, f"{seed['id']}: {codes}")
            self.assertEqual(linkedin_draft.slop_findings(seed["text"]), [], seed["id"])

    def test_generation_stamps_the_seed_and_puts_it_in_the_prompt(self) -> None:
        captured: list[list[dict[str, str]]] = []

        def complete(messages: list[dict[str, str]]):
            captured.append(messages)
            return (
                {"body": "A short hook.\n\nOne lesson.", "firstComment": "", "hashtags": [], "pillar": ""},
                0.01,
            )

        result = linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        post = result["posts"][0]
        self.assertIn(post["seedId"], linkedin_seeds.seed_ids())
        self.assertEqual(post["ideaId"], "")
        seed_text = next(s["text"] for s in linkedin_seeds.SEEDS if s["id"] == post["seedId"])
        user = captured[0][1]["content"]
        self.assertIn(f"Situation: {seed_text}", user)
        self.assertIn("Keep its specifics", user)

    def test_slop_phrases_and_emoji_force_a_rewrite(self) -> None:
        findings = linkedin_draft.slop_findings("Here's the thing 🚀\n\nWe leverage synergy. Agree?")
        details = " ".join(row["detail"] for row in findings)
        self.assertIn("emoji", details)
        self.assertIn("here's the thing", details)
        self.assertIn("leverage", details)
        self.assertIn("agree?", details)
        self.assertEqual(linkedin_draft.slop_findings("The 20 KB cap on a Lambda policy broke our deploy."), [])
        self.assertEqual(linkedin_draft.slop_findings("A journeyman's unlocked door."), [])
        seen: list[list[dict[str, str]]] = []

        def complete(messages: list[dict[str, str]]):
            seen.append(messages)
            if len(seen) == 1:
                return (
                    {"body": "Here's the thing about cloud.\n\nIt is a journey.", "firstComment": "", "hashtags": [], "pillar": ""},
                    0.01,
                )
            return (
                {"body": "A 20 KB policy cap.\n\nOne lesson.", "firstComment": "", "hashtags": [], "pillar": ""},
                0.01,
            )

        parsed, _cost = linkedin_draft.draft_one(
            settings=linkedin_store.default_settings(),
            pillar="platforms",
            idea="",
            avoid=[],
            complete=complete,
        )
        self.assertEqual(len(seen), 2)
        self.assertIn("here's the thing", seen[1][1]["content"])
        self.assertIn("20 KB", parsed["body"])

    def test_system_prompt_carries_substance_rules(self) -> None:
        prompt = linkedin_draft._system_prompt(linkedin_store.default_settings())  # noqa: SLF001
        self.assertIn("Substance rules always apply.", prompt)
        self.assertIn("Write as I, never as a company 'we'", prompt)
        self.assertIn("one real situation", prompt)
        self.assertIn("in the order it happened", prompt)
        self.assertIn("No sensationalism, no wow.", prompt)
        self.assertIn("game-changer", prompt)
        self.assertIn("No emojis, arrows, or symbols", prompt)
        self.assertLess(prompt.index("Substance rules"), prompt.index("Voice"))

    def test_company_we_forces_a_rewrite_but_one_conversation_does_not(self) -> None:
        plural = linkedin_draft.slop_findings("We built it. Our team shipped it on Friday.")
        self.assertEqual(len(plural), 1)
        self.assertIn("Write as I, not we", plural[0]["detail"])
        self.assertIn("2 times", plural[0]["detail"])
        lunch = "I had lunch with a former colleague and we wondered why there was no list. So I built one."
        self.assertEqual(linkedin_draft.slop_findings(lunch), [])
        self.assertEqual(linkedin_draft.slop_findings("Power is not the same as powerful."), [])
        self.assertEqual(linkedin_draft.slop_findings(linkedin_store.STYLE_EXAMPLE), [])

    def test_style_example_is_a_setting_and_a_prompt_block(self) -> None:
        settings = linkedin_store.default_settings()
        self.assertEqual(settings["styleExample"], linkedin_store.STYLE_EXAMPLE)
        self.assertLessEqual(len(linkedin_store.STYLE_EXAMPLE), linkedin_store.STYLE_EXAMPLE_MAX)
        self.assertEqual(linkedin_store.overview(self.table)["styleExampleMax"], linkedin_store.STYLE_EXAMPLE_MAX)
        prompt = linkedin_draft._system_prompt(settings)  # noqa: SLF001
        self.assertIn("Example of the register, written by the author.", prompt)
        self.assertIn("Do not copy its structure, its opening formula, its closing move", prompt)
        self.assertIn("A post that reads like a rewrite of this example is wrong.", prompt)
        self.assertIn(f"---\n{linkedin_store.STYLE_EXAMPLE}\n---", prompt)
        self.assertLess(prompt.index("Voice"), prompt.index("Example of the register"))
        self.assertLess(prompt.index("Example of the register"), prompt.index("Reply with one JSON object"))
        self.assertEqual(
            linkedin_draft.style_example_hook(settings),
            "Here is about building my AI exec board and its AI staff.",
        )
        blank = linkedin_draft._system_prompt({**settings, "styleExample": "  "})  # noqa: SLF001
        self.assertNotIn("Example of the register", blank)
        self.assertNotIn("---", blank)
        self.assertEqual(linkedin_draft.style_example_hook({**settings, "styleExample": ""}), "")

    def test_recommended_voice_quotes_no_catchphrase(self) -> None:
        voice = linkedin_store.RECOMMENDED_VOICE
        self.assertNotIn("So I built it", voice)
        self.assertNotIn("done is better than perfect", voice)
        self.assertNotIn("Here is about", voice)
        self.assertIn("no stock opening line, no stock closing line", voice)
        prompt = linkedin_draft._system_prompt(linkedin_store.default_settings())  # noqa: SLF001
        self.assertIn("Each post has its own opening and its own ending", prompt)

    def test_repeat_findings_catch_a_template_and_pass_a_distinct_post(self) -> None:
        example = linkedin_store.STYLE_EXAMPLE
        template = (
            "Here is about the week I lost to a 20 KB limit.\n\nIt broke on Tuesday.\n\n"
            "I know what you're thinking - this is in the docs. Yes. Eventually done is better than perfect."
        )
        details = [row["detail"] for row in linkedin_draft.repeat_findings(template, [example])]
        self.assertEqual(len(details), 2)
        self.assertIn("Opens the same way as another post (“here is about…”)", details[0])
        self.assertIn("Ends the same way as another post (“i know what you're…”)", details[1])
        self.assertTrue(all(row["code"] == "repeat" for row in linkedin_draft.repeat_findings(template, [example])))
        distinct = (
            "The deploy failed at 20 KB.\n\nI had added one route too many.\n\n"
            "The policy is now one statement. The limit has not moved."
        )
        self.assertEqual(linkedin_draft.repeat_findings(distinct, [example, template]), [])
        phrase = "A different first line.\n\nOn a good day, it runs without supervision for 15-20 hours, which I did not expect.\n\nThat is where it is."
        shared = linkedin_draft.repeat_findings(phrase, [example])
        self.assertEqual(len(shared), 1)
        self.assertIn("Shares the phrase “", shared[0]["detail"])
        self.assertIn("runs without supervision", shared[0]["detail"])
        self.assertEqual(linkedin_draft.repeat_findings("Short.\n\nDone.", ["Short.\n\nDone."]), [])
        self.assertEqual(linkedin_draft.repeat_findings(template, ["", "   "]), [])

    def test_each_draft_in_a_batch_gets_its_own_shape(self) -> None:
        shapes = [linkedin_draft.shape_for(i, 0) for i in range(6)]
        self.assertEqual(len({row["open"] for row in shapes}), 6)
        self.assertEqual(len({row["close"] for row in shapes}), 6)
        self.assertEqual(len({(row["open"], row["close"]) for row in shapes}), 6)
        self.assertNotEqual(linkedin_draft.shape_for(0, 0), linkedin_draft.shape_for(0, 4))
        self.assertEqual(linkedin_draft.shape_for(2, 3), linkedin_draft.shape_for(5, 0))
        self.assertEqual(linkedin_draft.DRAFT_TEMPERATURE, 0.9)

    def test_batch_drafts_see_each_other_and_a_copy_is_rewritten(self) -> None:
        captured: list[list[dict[str, str]]] = []
        first = (
            "The alarm fired at 03:10.\n\nI had let one function call itself.\n\n"
            "The cap is 250 invocations in five minutes, and I have not needed to raise it."
        )
        copy = (
            "The alarm fired at 03:10 again.\n\nA different function this time.\n\n"
            "The cap is 250 invocations in five minutes, and I have not touched it."
        )
        fixed = "A 20 KB policy cap.\n\nOne route too many.\n\nThe policy is one statement now."
        later = "Pillow needs an arm64 wheel.\n\nThe x86 runner built the wrong one.\n\nQEMU is registered first now."
        drafts = iter([first, copy, later])

        def complete(messages: list[dict[str, str]]):
            captured.append(messages)
            user = messages[1]["content"]
            if user.startswith("Rewrite this post"):
                return ({"body": fixed, "firstComment": "", "hashtags": [], "pillar": ""}, 0.01)
            return ({"body": next(drafts), "firstComment": "", "hashtags": [], "pillar": ""}, 0.01)

        result = linkedin_draft.generate_drafts(self.table, count=2, complete=complete)
        bodies = [row["body"] for row in result["posts"]]
        self.assertEqual(bodies, [first, fixed])
        self.assertEqual(len(captured), 3)
        one, two, critic = (row[1]["content"] for row in captured)
        self.assertIn("Shape for this post", one)
        self.assertIn(f"open with {linkedin_draft.OPENINGS[0]}", one)
        self.assertIn(f"open with {linkedin_draft.OPENINGS[1]}", two)
        self.assertIn("Do not reuse these closing lines:", one)
        self.assertIn("- I know what you're thinking - AI is going to mess up", one)
        self.assertIn("- The alarm fired at 03:10.", two)
        self.assertIn(f"- {linkedin_store.closing_text(first)}", two)
        self.assertIn("Opens the same way as another post", critic)
        self.assertIn("Shares the phrase", critic)
        self.assertIn(f"open with {linkedin_draft.OPENINGS[1]}", critic)
        again = linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        self.assertIn(f"open with {linkedin_draft.OPENINGS[2]}", captured[-1][1]["content"])
        self.assertIn(f"- {linkedin_store.hook_text(fixed)}", captured[-1][1]["content"])
        self.assertEqual(len(again["posts"]), 1)

    def test_style_example_saves_blank_and_rejects_over_length(self) -> None:
        saved = linkedin_store.save_settings(
            self.table, {**linkedin_store.default_settings(), "styleExample": "  A post I wrote.  "}
        )
        self.assertEqual(saved["styleExample"], "A post I wrote.")
        self.assertEqual(linkedin_store.load_settings(self.table)["styleExample"], "A post I wrote.")
        cleared = linkedin_store.save_settings(self.table, {**saved, "styleExample": ""})
        self.assertEqual(cleared["styleExample"], "")
        self.assertEqual(linkedin_store.load_settings(self.table)["styleExample"], "")
        with self.assertRaises(LinkedInError):
            linkedin_store.save_settings(
                self.table, {**saved, "styleExample": "x" * (linkedin_store.STYLE_EXAMPLE_MAX + 1)}
            )

    def test_generation_keeps_the_example_opening_off_new_drafts(self) -> None:
        captured: list[list[dict[str, str]]] = []

        def complete(messages: list[dict[str, str]]):
            captured.append(messages)
            return (
                {"body": "A short hook.\n\nOne lesson.", "firstComment": "", "hashtags": [], "pillar": ""},
                0.01,
            )

        linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        user = captured[0][1]["content"]
        self.assertIn("Do not reuse these openings:", user)
        self.assertIn("- Here is about building my AI exec board and its AI staff.", user)
        self.assertIn("Do not reuse these closing lines:", user)
        self.assertIn("Example of the register", captured[0][0]["content"])

    def test_openrouter_error_becomes_a_failed_generation(self) -> None:
        from openrouter_client import OpenRouterError

        def complete(_messages):
            raise OpenRouterError("linkedin key missing")

        with self.assertRaises(LinkedInError) as caught:
            linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        self.assertIn("linkedin key missing", str(caught.exception))

    def test_model_hashtags_drop_invalid_tags(self) -> None:
        parsed = linkedin_draft.parse_draft(
            '{"body":"A short hook.\\n\\nOne lesson.","firstComment":"","hashtags":["good-tag","Architecture"],"pillar":"architecture"}'
        )
        self.assertEqual(parsed["hashtags"], ["Architecture"])

    def test_parse_draft_accepts_fenced_json_and_raw_newlines(self) -> None:
        parsed = linkedin_draft.parse_draft(
            "Here is the post:\n```json\n"
            '{\n  "body": "A short hook.\n\nOne lesson.",\n'
            '  "firstComment": "",\n  "hashtags": ["Architecture"],\n'
            '  "pillar": "architecture"\n}\n```\n'
        )
        self.assertEqual(parsed["body"], "A short hook.\n\nOne lesson.")
        self.assertEqual(parsed["hashtags"], ["Architecture"])

    def test_parse_draft_rejects_empty_and_non_json(self) -> None:
        with self.assertRaises(linkedin_draft.DraftError):
            linkedin_draft.parse_draft("")
        with self.assertRaises(linkedin_draft.DraftError):
            linkedin_draft.parse_draft("I drafted a post but will not use JSON.")
        with self.assertRaises(linkedin_draft.DraftError) as caught:
            linkedin_draft.parse_draft(
                '{"body":"","firstComment":"","hashtags":[],"pillar":"architecture"}'
            )
        self.assertIn("empty post", str(caught.exception))

    def test_parse_draft_reads_alternate_body_fields(self) -> None:
        from_text = linkedin_draft.parse_draft(
            '{"text":"A short hook.\\n\\nOne lesson.","hashtags":["Architecture"]}'
        )
        self.assertEqual(from_text["body"], "A short hook.\n\nOne lesson.")
        from_lines = linkedin_draft.parse_draft(
            '{"body":["A short hook.","One lesson."],"hashtags":["Architecture"]}'
        )
        self.assertEqual(from_lines["body"], "A short hook.\nOne lesson.")

    def test_system_prompt_does_not_show_an_empty_body(self) -> None:
        prompt = linkedin_draft._system_prompt(linkedin_store.default_settings())  # noqa: SLF001
        self.assertNotIn('"body":""', prompt)
        self.assertIn("never an empty string", prompt)
        self.assertNotIn("What would you have done?", prompt)
        self.assertIn("The full post goes here.", prompt)
        self.assertIn("do not copy its wording", prompt)

    def test_system_prompt_includes_voice(self) -> None:
        voice = "Short sentences. Dry. No emoji."
        settings = {**linkedin_store.default_settings(), "voiceNotes": voice}
        prompt = linkedin_draft._system_prompt(settings)  # noqa: SLF001
        self.assertIn("Voice — follow this exactly.", prompt)
        self.assertIn("overrides the tone defaults", prompt)
        self.assertIn("The voice cannot override them.", prompt)
        self.assertLess(prompt.index("Tone defaults"), prompt.index(voice))
        self.assertIn(f"\n{voice}", prompt)
        self.assertNotIn(f"{voice} Write in the first person", prompt)
        blank = linkedin_draft._system_prompt({**settings, "voiceNotes": "  "})  # noqa: SLF001
        self.assertIn("Voice: none. Use the tone defaults.", blank)
        self.assertNotIn(voice, blank)
        self.assertNotIn("follow this exactly", blank)

    def test_live_generation_books_usage(self) -> None:
        from openrouter_client import ChatCompletion
        from openrouter_usage import usage_day_pk, utc_today

        completion = ChatCompletion(
            text='{"body":"A short hook.\\n\\nOne lesson.","firstComment":"","hashtags":["Architecture"],"pillar":"architecture"}',
            model="test-model",
            usage={"promptTokens": 11, "completionTokens": 22, "totalTokens": 33, "cost": 0.03},
        )
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test-model"}):
            with patch("openrouter_client.chat_completion", return_value=completion) as chat:
                result = linkedin_draft.generate_drafts(self.table, count=1)
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(chat.call_args.kwargs["model"], "test-model")
        item = self.table.items[(usage_day_pk(utc_today()), "linkedin#draft")]
        self.assertEqual(item["calls"], 1)
        self.assertEqual(item["promptTokens"], 11)
        self.assertEqual(item["costCenter"], "lxSoftware")
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.03)

    def test_complete_json_logs_unparseable_model_text(self) -> None:
        from openrouter_client import ChatCompletion

        completion = ChatCompletion(
            text="not json",
            model="test-model",
            finish_reason="stop",
            usage={"promptTokens": 1, "completionTokens": 1, "totalTokens": 2, "cost": 0.01},
        )
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test-model"}):
            with patch("openrouter_client.chat_completion", return_value=completion) as chat:
                with patch.object(linkedin_draft, "_log_event") as log:
                    with self.assertRaises(linkedin_draft.DraftError):
                        linkedin_draft.complete_json([{"role": "user", "content": "x"}])
        self.assertEqual(log.call_args.kwargs["tag"], "linkedin_draft_parse_failed")
        self.assertEqual(log.call_args.kwargs["text_len"], 8)
        self.assertEqual(log.call_args.kwargs["model"], "test-model")
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args.kwargs["reasoning"], {"enabled": False, "exclude": True})

    def test_a_cut_off_reply_retries_with_more_room_then_names_the_model(self) -> None:
        from openrouter_client import ChatCompletion

        thinking = ChatCompletion(
            text="The user wants a LinkedIn post about " + "x" * 5000,
            model="qwen/qwen3.7-plus",
            finish_reason="length",
            usage={"promptTokens": 1, "completionTokens": 1200, "totalTokens": 1201, "cost": 0.02},
        )
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "qwen/qwen3.7-plus"}):
            with patch("openrouter_client.chat_completion", return_value=thinking) as chat:
                with self.assertRaises(linkedin_draft.DraftError) as caught:
                    linkedin_draft.complete_json([{"role": "user", "content": "x"}])
        self.assertEqual(chat.call_count, 2)
        first, second = chat.call_args_list
        self.assertEqual(first.kwargs["max_tokens"], linkedin_draft.DRAFT_MAX_TOKENS)
        self.assertEqual(second.kwargs["max_tokens"], linkedin_draft.DRAFT_RETRY_MAX_TOKENS)
        self.assertIn("cut off", second.kwargs["messages"][-1]["content"])
        self.assertTrue(caught.exception.stop)
        self.assertIn("qwen/qwen3.7-plus", str(caught.exception))
        self.assertIn("non-reasoning model", str(caught.exception))

    def test_a_cut_off_reply_that_still_contains_the_json_is_used(self) -> None:
        from openrouter_client import ChatCompletion

        fixed = ChatCompletion(
            text='<think>short</think>{"body":"A short hook.\\n\\nOne lesson.","hashtags":[]}',
            model="qwen/qwen3.7-plus",
            finish_reason="stop",
            usage={"cost": 0.01},
        )
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "qwen/qwen3.7-plus"}):
            with patch("openrouter_client.chat_completion", return_value=fixed):
                parsed, cost = linkedin_draft.complete_json([{"role": "user", "content": "x"}])
        self.assertEqual(parsed["body"], "A short hook.\n\nOne lesson.")
        self.assertAlmostEqual(cost, 0.01)

    def test_a_stop_error_ends_the_batch_after_one_topic(self) -> None:
        calls: list[int] = []

        def complete(_messages):
            calls.append(1)
            raise linkedin_draft.DraftError("model kept thinking", stop=True)

        with self.assertRaises(LinkedInError) as caught:
            linkedin_draft.generate_drafts(self.table, count=3, complete=complete)
        self.assertEqual(len(calls), 1)
        self.assertIn("model kept thinking", str(caught.exception))

    def test_a_plain_draft_error_moves_to_the_next_topic(self) -> None:
        calls: list[int] = []

        def complete(_messages):
            calls.append(1)
            if len(calls) == 1:
                raise linkedin_draft.DraftError("The model returned an empty post.")
            return (
                {"body": "A short hook.\n\nOne lesson.", "firstComment": "", "hashtags": [], "pillar": ""},
                0.01,
            )

        result = linkedin_draft.generate_drafts(self.table, count=2, complete=complete)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["errors"], ["The model returned an empty post."])

    def test_live_generation_uses_settings_model(self) -> None:
        from openrouter_client import ChatCompletion

        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "model": "openai/gpt-4.1-mini"},
        )
        completion = ChatCompletion(
            text='{"body":"A short hook.\\n\\nOne lesson.","firstComment":"","hashtags":["Architecture"],"pillar":"architecture"}',
            model="openai/gpt-4.1-mini",
            usage={"promptTokens": 4, "completionTokens": 6, "totalTokens": 10, "cost": 0.01},
        )
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test-model"}):
            with patch("openrouter_client.chat_completion", return_value=completion) as chat:
                linkedin_draft.generate_drafts(self.table, count=1)
        self.assertEqual(chat.call_args.kwargs["model"], "openai/gpt-4.1-mini")

    def test_live_generation_sends_voice_to_openrouter(self) -> None:
        from openrouter_client import ChatCompletion

        voice = "Short sentences. Dry. No emoji."
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "voiceNotes": voice},
        )
        completion = ChatCompletion(
            text='{"body":"A short hook.\\n\\nOne lesson.","firstComment":"","hashtags":["Architecture"],"pillar":"architecture"}',
            model="test-model",
            usage={"promptTokens": 4, "completionTokens": 6, "totalTokens": 10, "cost": 0.01},
        )
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "test-model"}):
            with patch("openrouter_client.chat_completion", return_value=completion) as chat:
                linkedin_draft.generate_drafts(self.table, count=1)
        messages = chat.call_args.kwargs["messages"]
        self.assertIn("Voice — follow this exactly.", messages[0]["content"])
        self.assertIn(voice, messages[0]["content"])
        self.assertIn(f"Voice: {voice}", messages[1]["content"])
        self.assertLess(messages[1]["content"].index("Voice:"), messages[1]["content"].index("Pillar:"))

    def test_user_prompt_includes_voice(self) -> None:
        text = linkedin_draft._user_prompt(  # noqa: SLF001
            pillar="architecture",
            idea="A rollback that took too long.",
            voice="Dry, first person, one lesson.",
            avoid=[],
        )
        self.assertIn("Voice: Dry, first person, one lesson.", text)
        self.assertIn("overrides the tone defaults", text)
        self.assertLess(text.index("Voice:"), text.index("Pillar:"))
        blank = linkedin_draft._user_prompt(  # noqa: SLF001
            pillar="architecture",
            idea="A rollback that took too long.",
            voice="  ",
            avoid=[],
        )
        self.assertNotIn("Voice:", blank)

    def test_generation_puts_saved_voice_in_the_model_messages(self) -> None:
        voice = "Short sentences. Dry. No emoji."
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "voiceNotes": voice},
        )
        captured: list[list[dict[str, str]]] = []

        def complete(messages: list[dict[str, str]]):
            captured.append(messages)
            return (
                {"body": "A short hook.\n\nOne lesson.", "firstComment": "", "hashtags": [], "pillar": ""},
                0.01,
            )

        result = linkedin_draft.generate_drafts(self.table, count=1, complete=complete)
        self.assertEqual(len(result["posts"]), 1)
        self.assertEqual(result["posts"][0]["generation"]["voiceHash"], linkedin_draft.voice_hash({"voiceNotes": voice}))
        self.assertEqual(len(captured), 1)
        system, user = captured[0]
        self.assertIn("Voice — follow this exactly.", system["content"])
        self.assertIn(voice, system["content"])
        self.assertIn(f"Voice: {voice}", user["content"])

    def test_voice_hash_changes_with_the_saved_voice(self) -> None:
        first = linkedin_draft.voice_hash({"voiceNotes": "Dry."})
        second = linkedin_draft.voice_hash({"voiceNotes": "Warm."})
        blank = linkedin_draft.voice_hash({"voiceNotes": "  "})
        self.assertEqual(len(first), 16)
        self.assertNotEqual(first, second)
        self.assertEqual(blank, linkedin_draft.voice_hash({}))

    def test_guardrail_rewrite_restates_the_voice(self) -> None:
        voice = "Short sentences. Dry. No emoji."
        seen: list[list[dict[str, str]]] = []

        def complete(messages: list[dict[str, str]]):
            seen.append(messages)
            if len(seen) == 1:
                return (
                    {"body": "I am open to work.\n\nOne lesson.", "firstComment": "", "hashtags": [], "pillar": ""},
                    0.01,
                )
            return (
                {"body": "A short hook.\n\nOne lesson.", "firstComment": "", "hashtags": [], "pillar": ""},
                0.01,
            )

        linkedin_draft.draft_one(
            settings={**linkedin_store.default_settings(), "voiceNotes": voice},
            pillar="architecture",
            idea="",
            avoid=[],
            complete=complete,
        )
        self.assertEqual(len(seen), 2)
        rewrite = seen[1][1]["content"]
        self.assertIn(f"Keep this voice exactly: {voice}", rewrite)
        self.assertIn("overrides the tone defaults", rewrite)
        quiet = linkedin_draft._critic_messages(  # noqa: SLF001
            {**linkedin_store.default_settings(), "voiceNotes": ""},
            {"body": "A short hook."},
            [{"severity": "error", "detail": "The first line is too long."}],
        )
        self.assertNotIn("Keep this voice exactly:", quiet[1]["content"])

    def test_regenerate_stamps_the_voice_hash(self) -> None:
        voice = "Short sentences. Dry. No emoji."
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "voiceNotes": voice},
        )
        doc = linkedin_store.create_post(
            self.table,
            {"body": "A short hook.\n\nOne lesson."},
            generation={"model": "old", "jobId": "job_old", "voiceHash": "stale"},
        )
        linkedin._replace_post(  # noqa: SLF001
            self.table,
            doc["postId"],
            {
                "body": "A different hook.\n\nOne lesson.",
                "firstComment": "",
                "hashtags": [],
                "pillar": "architecture",
            },
        )
        stored = linkedin_store.get_post(self.table, doc["postId"]) or {}
        generation = stored.get("generation") or {}
        self.assertEqual(generation["voiceHash"], linkedin_draft.voice_hash({"voiceNotes": voice}))
        self.assertEqual(generation["jobId"], "job_old")
        self.assertNotEqual(generation["voiceHash"], "stale")
        self.assertIn("different hook", stored["body"])


class LinkedInHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()
        linkedin_api.reset_credentials_cache_for_tests()
        patcher = patch.object(runtime, "_ddb")
        mock_ddb = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ddb.Table.return_value = self.table
        self.env = patch.dict("os.environ", ENABLED, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_writes_are_refused_when_the_switch_is_off(self) -> None:
        with patch.dict("os.environ", {"LINKEDIN_ENABLED": "false"}):
            overview = lambda_handler(_event("/lx-software/linkedin"), None)
            self.assertEqual(overview["statusCode"], 200)
            self.assertFalse(_body(overview)["enabled"])
            created = lambda_handler(
                _event("/lx-software/linkedin/posts", "POST", {"body": "A short hook."}),
                None,
            )
            self.assertEqual(created["statusCode"], 403)

    def test_settings_put_stores_model_and_overview_exposes_default(self) -> None:
        with patch.dict("os.environ", {"OPENROUTER_MODEL": "mistralai/mistral-medium-3"}):
            overview = lambda_handler(_event("/lx-software/linkedin"), None)
            self.assertEqual(_body(overview)["defaultModel"], "mistralai/mistral-medium-3")
            saved = lambda_handler(
                _event(
                    "/lx-software/linkedin/settings",
                    "PUT",
                    {**linkedin_store.default_settings(), "model": "openai/gpt-4.1-mini"},
                ),
                None,
            )
        self.assertEqual(saved["statusCode"], 200)
        self.assertEqual(_body(saved)["settings"]["model"], "openai/gpt-4.1-mini")

    def test_create_approve_and_mark_posted(self) -> None:
        created = lambda_handler(
            _event(
                "/lx-software/linkedin/posts",
                "POST",
                {"body": "A short hook.\n\nOne lesson.", "pillar": "platforms"},
            ),
            None,
        )
        self.assertEqual(created["statusCode"], 201)
        post_id = _body(created)["item"]["postId"]
        approved = lambda_handler(
            _event(f"/lx-software/linkedin/posts/{post_id}/approve", "POST", {}),
            None,
        )
        self.assertEqual(approved["statusCode"], 200)
        self.assertEqual(_body(approved)["item"]["status"], "approved")
        posted = lambda_handler(
            _event(
                f"/lx-software/linkedin/posts/{post_id}/mark-posted",
                "POST",
                {"url": "https://www.linkedin.com/feed/update/urn:li:share:9"},
            ),
            None,
        )
        self.assertEqual(_body(posted)["item"]["status"], "published")

    def test_due_reminder_sends_once(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nDue now."})
        doc["status"] = "approved"
        doc["slotAt"] = "2020-01-01T00:30:00.000Z"
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_settings(self.table, {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"})
        with patch.object(linkedin, "send_notice", return_value=True) as send:
            first = linkedin.handle_publish_due({})
            second = linkedin.handle_publish_due({})
        self.assertEqual(first["reminded"], 1)
        self.assertEqual(second["reminded"], 0)
        send.assert_called_once()
        self.assertIn("linkedin-post=", send.call_args.args[2])

    def test_publish_switch_does_not_post(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nDue now."})
        doc["status"] = "approved"
        doc["slotAt"] = "2020-01-01T00:30:00.000Z"
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"},
        )
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                result = linkedin.handle_publish_due({})
        self.assertEqual(result["reminded"], 1)
        self.assertEqual(result["published"], 0)
        self.assertEqual(result["publish"], "not_connected")
        self.assertNotIn("skipped", result)
        send.assert_called_once()
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["status"], "approved")

    def test_generate_without_a_job_does_not_draft(self) -> None:
        result = linkedin.handle_generate({})
        self.assertEqual(result, {"skipped": "missing_job"})
        self.assertEqual(linkedin_store.list_posts(self.table), [])

    def test_worker_error_marks_the_job_failed(self) -> None:
        from openrouter_client import OpenRouterError

        job = linkedin_store.new_job(self.table, "generate", {"count": 1})
        with patch.object(linkedin_draft, "generate_drafts", side_effect=OpenRouterError("linkedin key missing")):
            result = linkedin.handle_generate({"jobId": job["jobId"]})
        self.assertFalse(result["ok"])
        stored = linkedin_store.get_job(self.table, job["jobId"])
        self.assertEqual(stored["status"], "failed")
        self.assertIn("linkedin key missing", stored["error"])

        unknown = linkedin_store.new_job(self.table, "generate", {"count": 1})
        with patch.object(linkedin_draft, "generate_drafts", side_effect=RuntimeError("boom")):
            failed = linkedin.handle_generate({"jobId": unknown["jobId"]})
        self.assertEqual(failed["error"], "Generation failed.")
        self.assertEqual(linkedin_store.get_job(self.table, unknown["jobId"])["status"], "failed")

    def test_bad_replacement_hashtag_fails_the_job(self) -> None:
        post = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nKeep this id."})
        job = linkedin_store.new_job(self.table, "generate", {"postId": post["postId"]})
        generated = {
            "body": "A short hook.\n\nA new lesson.",
            "firstComment": "",
            "hashtags": ["not-a-tag"],
            "pillar": "architecture",
        }
        with patch.object(
            linkedin_draft,
            "generate_drafts",
            return_value={"posts": [generated], "errors": [], "spendUsd": 0},
        ):
            result = linkedin.handle_generate({"jobId": job["jobId"]})
        self.assertFalse(result["ok"])
        stored = linkedin_store.get_job(self.table, job["jobId"])
        self.assertEqual(stored["status"], "failed")
        self.assertIn("invalid", stored["error"])

    def test_idea_create_and_delete_are_audited(self) -> None:
        created = lambda_handler(
            _event("/lx-software/linkedin/ideas", "POST", {"text": "A lesson about reviews.", "pillar": "leadership"}),
            None,
        )
        self.assertEqual(created["statusCode"], 201)
        idea_id = _body(created)["item"]["ideaId"]
        deleted = lambda_handler(_event(f"/lx-software/linkedin/ideas/{idea_id}", "DELETE"), None)
        self.assertEqual(deleted["statusCode"], 200)
        actions = [str(item["sk"]) for item in self.table.items.values() if str(item.get("pk")) == "USER#admin-sub"]
        self.assertTrue(any(action.endswith("#LINKEDIN_IDEA_CREATE") for action in actions))
        self.assertTrue(any(action.endswith("#LINKEDIN_IDEA_DELETE") for action in actions))

    def test_due_post_publishes_comment_and_image(self) -> None:
        doc = linkedin_store.create_post(
            self.table,
            {
                "body": "A short hook.\n\nOne lesson (keep it).",
                "firstComment": "The longer note lives here.",
                "hashtags": ["Architecture"],
            },
        )
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_post_image(self.table, doc["postId"], "image/png", b"\x89PNG\r\n\x1a\nrest")
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "refreshToken": "refresh-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "memberName": "Example Member",
                "channel": "profile",
                "organizations": [{"id": "99", "name": "Example Page"}],
            },
        )
        calls: list[str] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del headers, body
            calls.append(f"{method} {url}")
            if url.endswith("/images?action=initializeUpload"):
                return 200, {}, b'{"value":{"uploadUrl":"https://upload.example/img","image":"urn:li:image:1"}}'
            if url == "https://upload.example/img":
                return 201, {}, b""
            if url.endswith("/posts"):
                return 201, {"x-restli-id": "urn:li:share:1"}, b""
            if url.endswith("/comments"):
                return 201, {}, b""
            if "/socialActions/" in url:
                return 200, {}, b'{"likesSummary":{"totalLikes":4},"commentsSummary":{"aggregatedTotalComments":2}}'
            return 404, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            result = linkedin.handle_publish_due({})
        self.assertEqual(result["published"], 1)
        self.assertEqual(result["reminded"], 0)
        self.assertEqual(result["publish"], "posted")
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["status"], "published")
        self.assertEqual(stored["platform"]["urn"], "urn:li:share:1")
        self.assertEqual(stored["metrics"]["reactions"], 4)
        self.assertEqual(stored["metrics"]["comments"], 2)
        self.assertTrue(any("/comments" in call for call in calls))
        self.assertTrue(any("initializeUpload" in call for call in calls))

    def test_publish_failure_reminds_once_and_keeps_the_draft_approved(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nStill waiting."})
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "refreshToken": "refresh-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"},
        )

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, url, headers, body
            return 422, {}, b'{"message":"commentary rejected"}'

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                result = linkedin.handle_publish_due({})
        self.assertEqual(result["published"], 0)
        self.assertEqual(result["reminded"], 1)
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["publishAttempts"], 1)
        self.assertIn("commentary rejected", stored["publishError"])
        self.assertIn("Automatic posting failed", send.call_args.args[2])

    def test_a_slot_older_than_three_hours_stays_for_the_share_box(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nToo old to post."})
        doc["status"] = "approved"
        doc["slotAt"] = "2020-01-01T00:30:00.000Z"
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"},
        )
        calls: list[str] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            calls.append(url)
            return 201, {"x-restli-id": "urn:li:share:1"}, b""

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                result = linkedin.handle_publish_due({})
        self.assertEqual(result["published"], 0)
        self.assertEqual(result["reminded"], 1)
        self.assertEqual(calls, [])
        self.assertIn("three hours", send.call_args.args[2])
        self.assertEqual(linkedin_store.get_post(self.table, doc["postId"])["status"], "approved")

    def test_only_one_due_post_goes_out_per_tick(self) -> None:
        first = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nFirst."})
        second = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nSecond."})
        for doc, minutes in ((first, 40), (second, 10)):
            doc["status"] = "approved"
            doc["slotAt"] = _recent_slot(minutes)
            linkedin_store.put_post(self.table, doc)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            if url.endswith("/posts"):
                return 201, {"x-restli-id": "urn:li:share:1"}, b""
            return 200, {}, b'{"likesSummary":{"totalLikes":0},"commentsSummary":{"aggregatedTotalComments":0}}'

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            result = linkedin.handle_publish_due({})
        self.assertEqual(result["published"], 1)
        self.assertEqual(linkedin_store.get_post(self.table, first["postId"])["status"], "published")
        self.assertEqual(linkedin_store.get_post(self.table, second["postId"])["status"], "approved")

    def test_an_expired_token_does_not_use_up_attempts(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nNeeds a new login."})
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "tokenExpiresAt": "2000-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"},
        )
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                result = linkedin.handle_publish_due({})
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(result["published"], 0)
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(int(stored.get("publishAttempts") or 0), 0)
        self.assertIn("Reconnect LinkedIn", stored["publishError"])
        self.assertIn("Reconnect LinkedIn", send.call_args.args[2])

    def test_the_third_failure_says_posting_stopped(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nLast try."})
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        doc["publishAttempts"] = 2
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        linkedin_store.save_settings(
            self.table,
            {**linkedin_store.default_settings(), "notifyEmail": "owner@example.com"},
        )

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, url, headers, body
            return 422, {}, b'{"message":"commentary rejected"}'

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            with patch.object(linkedin, "send_notice", return_value=True) as send:
                result = linkedin.handle_publish_due({})
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(result["gaveUp"], 1)
        self.assertEqual(result["reminded"], 0)
        self.assertEqual(stored["publishAttempts"], 3)
        self.assertEqual(stored["status"], "approved")
        self.assertIn("will not be tried again", send.call_args.args[2])

    def test_a_recorded_urn_is_not_posted_twice(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nAlready created."})
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        created: list[str] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            if url.endswith("/posts"):
                created.append(url)
                return 201, {"x-restli-id": "urn:li:share:7"}, b""
            if "/socialActions/" in url and not url.endswith("/comments"):
                return 200, {}, b'{"likesSummary":{"totalLikes":1},"commentsSummary":{"aggregatedTotalComments":0}}'
            return 201, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        real_mark = linkedin_store.mark_api_published
        failed = {"once": False}

        def flaky_mark(*args, **kwargs):
            if not failed["once"]:
                failed["once"] = True
                raise RuntimeError("ddb down")
            return real_mark(*args, **kwargs)

        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            with patch.object(linkedin_store, "mark_api_published", flaky_mark):
                first = linkedin.handle_publish_due({})
                second = linkedin.handle_publish_due({})
        self.assertEqual(first["published"], 0)
        self.assertEqual(second["published"], 1)
        self.assertEqual(created, ["https://api.linkedin.com/rest/posts"])
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["status"], "published")
        self.assertEqual(stored["platform"]["urn"], "urn:li:share:7")

    def test_a_denied_metrics_read_is_not_retried(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nNo analytics."})
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        linkedin_store.put_post(self.table, doc)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        social: list[str] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers, body
            if url.endswith("/posts"):
                return 201, {"x-restli-id": "urn:li:share:3"}, b""
            if "/socialActions/" in url:
                social.append(url)
                return 403, {}, b'{"message":"forbidden"}'
            return 404, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true"}):
            linkedin.handle_publish_due({})
            linkedin.handle_publish_due({})
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertTrue(stored["metrics"]["unavailable"])
        self.assertEqual(len(social), 1)

    def test_connect_keeps_company_pages_off_unless_asked(self) -> None:
        with patch.object(linkedin_api, "load_credentials", return_value=("client", "secret")):
            plain = lambda_handler(_event("/lx-software/linkedin/connect", "POST", {}), None)
            pages = lambda_handler(
                _event("/lx-software/linkedin/connect", "POST", {"includeOrganizations": True}),
                None,
            )
        self.assertEqual(plain["statusCode"], 200)
        self.assertNotIn("w_organization_social", _body(plain)["url"])
        self.assertIn("w_member_social", _body(plain)["url"])
        self.assertIn("w_organization_social", _body(pages)["url"])
        oauth = [item for item in self.table.items.values() if str(item.get("pk", "")).startswith("LINKEDIN#oauth#")]
        self.assertEqual(len(oauth), 2)
        self.assertTrue(all(int(item["expiresAt"]) > int(time.time()) for item in oauth))

    def test_generate_queues_a_job(self) -> None:
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            response = lambda_handler(_event("/lx-software/linkedin/generate", "POST", {"count": 1}), None)
        self.assertEqual(response["statusCode"], 202)
        invoke.assert_called_once()
        self.assertEqual(invoke.call_args.args[0]["internal"], "linkedin_generate")


class LinkedInImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = FakeTable()
        linkedin_store._IMAGE_MEMORY.clear()
        linkedin_store._CHARACTER_MEMORY.clear()
        # No live picture brief in these tests; one that wants the brief passes its own.
        self._brief = patch("linkedin_draft.picture_brief", return_value=({}, 0.0))
        self._brief.start()
        self.addCleanup(self._brief.stop)

    def test_the_caption_always_ends_with_a_mark(self) -> None:
        finish = linkedin_store.finish_caption
        self.assertEqual(finish("'This took longer than I expected'"), "This took longer than I expected.")
        self.assertEqual(finish("“Is this the queue?”"), "Is this the queue?")
        self.assertEqual(finish("Not again!"), "Not again!")
        self.assertEqual(finish("It's fine."), "It's fine.")
        self.assertEqual(finish("Well, "), "Well.")
        self.assertEqual(finish("   "), "")
        self.assertEqual(finish("'"), "")
        self.assertEqual(linkedin_store.caption_alt("Quite a pile"), "Quite a pile.")
        parsed = linkedin_draft.parse_draft(
            '{"body":"A short hook.\\n\\nOne lesson.","imageScene":"In a lift.",'
            '"imageExpression":"weary.","imageCaption":"Still waiting for the doors"}'
        )
        self.assertEqual(parsed["imageCaption"], "Still waiting for the doors.")
        self.assertEqual(parsed["imageExpression"], "weary")
        prompt = linkedin_draft._system_prompt(linkedin_store.default_settings())  # noqa: SLF001
        self.assertIn("ends with a full stop", prompt)
        self.assertIn("living the problem in the post", prompt)
        self.assertIn("scratching his head", prompt)
        self.assertIn("screen full of gibberish", prompt)
        self.assertIn("never serious", prompt)
        self.assertNotIn("Do not default to a man at a desk", prompt)
        self.assertIn("never serious", linkedin_store.RECOMMENDED_IMAGE_STYLE)
        drawn = linkedin_image.build_prompt(linkedin_store.default_settings(), "A desk.", "baffled")
        self.assertIn("Play it for a laugh", drawn)

    def test_the_owner_can_have_the_three_fields_written_again(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "Fourteen percent failed validation.\n\nOne lesson."})
        linkedin_store.put_post(
            self.table,
            {
                **doc,
                "image": {"status": "ready", "contentType": "image/png", "scene": "Old.", "caption": "Old line.", "expression": "deadpan"},
            },
        )
        calls: list[str] = []

        def brief(*, table, settings, body):
            calls.append(body)
            return (
                {
                    "imageScene": "At a desk, the author scratches his head at a screen of scribbles.",
                    "imageExpression": "baffled, one eyebrow up",
                    "imageCaption": "Fourteen percent of these people do not exist",
                },
                0.001,
            )

        stored = linkedin_image.write_brief(self.table, doc["postId"], brief=brief)
        self.assertIn("Fourteen percent failed validation.", calls[0])
        self.assertEqual(stored["image"]["caption"], "Fourteen percent of these people do not exist.")
        self.assertEqual(stored["image"]["expression"], "baffled, one eyebrow up")
        self.assertTrue(stored["image"]["scene"].startswith("At a desk"))
        # The ready picture is kept until the owner redraws.
        self.assertEqual(stored["image"]["status"], "ready")
        self.assertEqual(stored["image"]["contentType"], "image/png")
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.001)

        def broken(**_kwargs):
            raise RuntimeError("OpenRouter down")

        with self.assertRaises(LinkedInError) as caught:
            linkedin_image.write_brief(self.table, doc["postId"], brief=broken)
        self.assertIn("Could not write the scene", str(caught.exception))
        with self.assertRaises(LinkedInError):
            linkedin_image.write_brief(self.table, "missing", brief=brief)

    def test_a_post_with_no_picture_yet_shows_the_written_fields(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})

        def brief(**_kwargs):
            return ({"imageScene": "A desk.", "imageExpression": "weary", "imageCaption": "Fine"}, 0.0)

        stored = linkedin_image.write_brief(self.table, doc["postId"], brief=brief)
        public = linkedin_store.public_post(stored)
        self.assertIsNotNone(public["image"])
        self.assertEqual(public["image"]["caption"], "Fine.")
        self.assertNotIn("contentType", public["image"])
        self.assertNotEqual(public["image"]["status"], "ready")

    def test_the_brief_route_and_an_owner_written_post(self) -> None:
        patcher = patch.object(runtime, "_ddb")
        mock_ddb = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ddb.Table.return_value = self.table
        env = patch.dict("os.environ", ENABLED, clear=False)
        env.start()
        self.addCleanup(env.stop)
        self._brief.stop()
        with patch("board_async.try_invoke_event", return_value=True) as invoke:
            created = lambda_handler(
                _event("/lx-software/linkedin/posts", "POST", {"body": "The lift queue was the bottleneck.\n\nOne lesson."}),
                None,
            )
        self.assertEqual(created["statusCode"], 201)
        item = _body(created)["item"]
        # The owner's post gets a picture; the worker writes the three fields from the post.
        self.assertEqual(item["image"]["status"], "pending")
        self.assertEqual(invoke.call_args.args[0]["internal"], "linkedin_image")
        linkedin_store.put_post(self.table, {**linkedin_store.get_post(self.table, item["postId"]), "image": {"status": "failed"}})
        written = (
            {"imageScene": "At a desk, head scratched.", "imageExpression": "baffled", "imageCaption": "Why is it Tuesday"},
            0.002,
        )
        with patch("linkedin_draft.picture_brief", return_value=written):
            response = lambda_handler(_event(f"/lx-software/linkedin/posts/{item['postId']}/image/brief", "POST", {}), None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(_body(response)["item"]["image"]["caption"], "Why is it Tuesday.")
        self.assertEqual(_body(response)["item"]["image"]["expression"], "baffled")
        with patch("linkedin_draft.picture_brief", side_effect=RuntimeError("down")):
            failed = lambda_handler(_event(f"/lx-software/linkedin/posts/{item['postId']}/image/brief", "POST", {}), None)
        self.assertEqual(failed["statusCode"], 502)
        missing = lambda_handler(_event("/lx-software/linkedin/posts/nope/image/brief", "POST", {}), None)
        self.assertEqual(missing["statusCode"], 404)

    def test_a_post_without_a_brief_has_one_written_from_the_post(self) -> None:
        from openrouter_client import GeneratedImage, ImageGeneration

        doc = linkedin_store.create_post(
            self.table, {"body": "The migration took eleven hours.\n\nThe estimate was forty minutes."}
        )
        with patch("board_async.try_invoke_event", return_value=True):
            queued = linkedin_image.queue_for_post(self.table, doc["postId"])
        self.assertEqual(queued["image"]["scene"], "")
        self.assertEqual(queued["image"]["caption"], "")
        asked: dict[str, object] = {}

        def brief(*, table, settings, body):
            asked["body"] = body
            asked["settings"] = settings
            return (
                {
                    "imageScene": "In a car park, the author pushes a progress bar the length of a bus.",
                    "imageExpression": "weary, jaw set",
                    "imageCaption": "'Forty minutes, the estimate said'",
                },
                0.002,
            )

        seen: dict[str, object] = {}

        def generate(prompt, aspect, seed, references, settings, n=1):
            seen["prompt"] = prompt
            return ImageGeneration(
                images=[GeneratedImage("image/png", self._png())],
                model="bytedance-seed/seedream-4.5",
                usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost": 0.04},
            )

        result = linkedin_image.render_post(self.table, doc["postId"], generate=generate, brief=brief)
        self.assertTrue(result["ok"])
        self.assertIn("eleven hours", str(asked["body"]))
        self.assertIn("progress bar the length of a bus", str(seen["prompt"]))
        self.assertIn("Expression: weary, jaw set", str(seen["prompt"]))
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["image"]["status"], "ready")
        self.assertEqual(stored["image"]["caption"], "Forty minutes, the estimate said.")
        self.assertEqual(stored["image"]["expression"], "weary, jaw set")
        self.assertTrue(stored["image"]["scene"].startswith("In a car park"))
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.042)

    def test_a_failed_brief_still_draws_a_picture_about_the_post(self) -> None:
        from openrouter_client import GeneratedImage, ImageGeneration

        doc = linkedin_store.create_post(self.table, {"body": "The lift queue was the real bottleneck.\n\nOne lesson."})
        with patch("board_async.try_invoke_event", return_value=True):
            linkedin_image.queue_for_post(self.table, doc["postId"], caption="Still queueing")

        def brief(**_kwargs):
            raise RuntimeError("OpenRouter down")

        def generate(prompt, aspect, seed, references, settings, n=1):
            return ImageGeneration(
                images=[GeneratedImage("image/png", self._png())],
                model="bytedance-seed/seedream-4.5",
                usage={"cost": 0.01},
            )

        result = linkedin_image.render_post(self.table, doc["postId"], generate=generate, brief=brief)
        self.assertTrue(result["ok"])
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertIn("The lift queue was the real bottleneck.", stored["image"]["scene"])
        self.assertEqual(stored["image"]["caption"], "Still queueing.")
        self.assertEqual(stored["image"]["expression"], linkedin_store.FALLBACK_IMAGE_EXPRESSION)

    def test_the_picture_brief_is_asked_from_the_post_alone(self) -> None:
        captured: dict[str, object] = {}

        def fake(messages, *, table=None, settings=None):
            captured["messages"] = messages
            return (
                {"imageScene": "Scene.", "imageExpression": "deadpan", "imageCaption": "Is that it"},
                0.001,
            )

        self._brief.stop()
        with patch("linkedin_draft.complete_json_object", side_effect=fake):
            fields, cost = linkedin_draft.picture_brief(
                table=None, settings=linkedin_store.default_settings(), body="A short hook.\n\nOne lesson."
            )
        self.assertEqual(fields["imageCaption"], "Is that it.")
        self.assertEqual(cost, 0.001)
        messages = captured["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("living the problem in the post", messages[0]["content"])
        self.assertIn("A short hook.", messages[1]["content"])
        self.assertEqual(linkedin_draft.picture_brief(table=None, settings={}, body="  "), ({}, 0.0))

    def _png(self, color=(180, 30, 30), size=(90, 60)) -> bytes:
        from io import BytesIO

        from PIL import Image

        image = Image.new("RGB", size, color)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_settings_keep_the_picture_fields(self) -> None:
        settings = linkedin_store.default_settings()
        self.assertEqual(settings["imageModel"], "bytedance-seed/seedream-4.5")
        self.assertTrue(settings["imagesEnabled"])
        self.assertLessEqual(len(settings["imageStyle"]), linkedin_store.IMAGE_STYLE_MAX)
        self.assertLessEqual(len(settings["imageCharacter"]), linkedin_store.IMAGE_CHARACTER_MAX)
        overview = linkedin_store.overview(self.table)
        self.assertEqual(overview["imageModelAlternative"], "qwen/qwen-image-3")
        self.assertEqual(overview["recommendedImageStyle"], linkedin_store.RECOMMENDED_IMAGE_STYLE)
        with self.assertRaises(LinkedInError):
            linkedin_store.save_settings(self.table, {**settings, "imageFormat": "banner"})
        with self.assertRaises(LinkedInError):
            linkedin_store.save_settings(self.table, {**settings, "imageModel": "not a slug"})

    def test_compose_draws_the_caption_inside_the_picture(self) -> None:
        from io import BytesIO

        from PIL import Image

        sizes = {"square": (1200, 1200), "portrait": (1080, 1350), "wide": (1200, 675)}
        for fmt, size in sizes.items():
            png = linkedin_image.compose(self._png(), "'This took longer than I expected.'", fmt)
            image = Image.open(BytesIO(png))
            self.assertEqual(image.size, size)
            self.assertEqual(image.mode, "L")
            self.assertEqual(image.getpixel((0, 0)), 0)
            self.assertNotEqual(image.getpixel((80, 80)), 255)
            self.assertEqual(image.getpixel((48, size[1] - 50)), 255)
        lines = linkedin_image.caption_lines(  # noqa: SLF001
            "'This took longer than I expected.'",
            width=900,
            font=linkedin_image._font(44),  # noqa: SLF001
        )
        self.assertEqual(lines, ["This took longer than I expected."])
        self.assertNotIn("'", "".join(lines))
        prompt = linkedin_draft._system_prompt(linkedin_store.default_settings())  # noqa: SLF001
        self.assertIn("Picture.", prompt)
        self.assertIn("imageExpression", prompt)
        self.assertNotIn("single quotes", prompt.lower())

    def test_character_prompt_is_a_caricature_and_the_expression_is_sent(self) -> None:
        settings = linkedin_store.default_settings()
        character = linkedin_image.character_prompt(settings)
        self.assertIn("caricature", character)
        self.assertNotIn("smile", character.lower())
        prompt = linkedin_image.build_prompt(settings, "In a lift, a giant ticket blocks the door.", "alarmed")
        self.assertIn("Expression: alarmed", prompt)
        self.assertIn("Do not default to a smile", prompt)
        self.assertIn("lower edge", prompt)
        self.assertLessEqual(len(settings["imageStyle"]), linkedin_store.IMAGE_STYLE_MAX)
        parsed = linkedin_draft.parse_draft(
            '{"body":"A short hook.\\n\\nOne lesson.","imageScene":"In a lift, a giant ticket blocks the door.",'
            '"imageExpression":"deadpan","imageCaption":"\'Fine.\'"}'
        )
        self.assertEqual(parsed["imageExpression"], "deadpan")
        self.assertEqual(parsed["imageCaption"], "Fine.")
        repeated = linkedin_draft.scene_findings(
            "At a cluttered desk the author scratches his head at a screen of scribbles.",
            ["At a cluttered desk the author scratches his head at a wall of sticky notes."],
        )
        self.assertEqual(repeated[0]["code"], "scene")
        # A desk and a screen may come back; only the same wording is sent back.
        same_room = linkedin_draft.scene_findings(
            "At his desk, the author squints at a monitor showing a column of nonsense.",
            ["At a desk by the window, the author holds two cables and looks at a blank monitor."],
        )
        self.assertEqual(same_room, [])

    def test_a_product_name_in_the_scene_is_not_sent(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        linkedin_store.put_post(
            self.table,
            {
                **doc,
                "image": {"status": "pending", "scene": "The author holding a siutindei invoice.", "caption": "Quite a pile."},
            },
        )

        def generate(*_args, **_kwargs):
            raise AssertionError("the model must not be called")

        result = linkedin_image.render_post(self.table, doc["postId"], generate=generate)
        self.assertFalse(result["ok"])
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["image"]["status"], "failed")
        self.assertIn("siutindei", stored["image"]["error"])

    def test_render_stores_a_ready_png_and_books_the_cost(self) -> None:
        from openrouter_client import GeneratedImage, ImageGeneration

        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        linkedin_image.queue_for_post(self.table, doc["postId"], scene="The author under a tower of paper.", caption="Quite a pile.", force=True)
        seen: dict[str, object] = {}

        def generate(prompt, aspect, seed, references, settings, n=1):
            seen["prompt"] = prompt
            seen["aspect"] = aspect
            seen["n"] = n
            seen["references"] = references
            return ImageGeneration(
                images=[GeneratedImage("image/png", self._png())],
                model="bytedance-seed/seedream-4.5",
                usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost": 0.04},
            )

        result = linkedin_image.render_post(self.table, doc["postId"], generate=generate)
        self.assertTrue(result["ok"])
        self.assertEqual(seen["aspect"], "1:1")
        self.assertIn(linkedin_store.FALLBACK_IMAGE_EXPRESSION, str(seen["prompt"]))
        self.assertIsNone(seen["references"])
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["image"]["status"], "ready")
        self.assertEqual(stored["image"]["caption"], "Quite a pile.")
        loaded = linkedin_store.load_post_image(doc["postId"])
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded[1].startswith(b"\x89PNG"))
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.04)
        public = linkedin_store.public_post(stored)
        self.assertEqual(public["image"]["contentType"], "image/png")
        self.assertEqual(public["image"]["status"], "ready")

    def test_redraw_is_refused_while_one_is_pending(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        with patch("board_async.try_invoke_event", return_value=True):
            linkedin_image.queue_for_post(self.table, doc["postId"], scene="A desk.", caption="Fine.")
            with self.assertRaises(LinkedInError) as caught:
                linkedin_image.queue_for_post(self.table, doc["postId"], scene="A desk.", caption="Fine.")
        self.assertIn("already being drawn", str(caught.exception))

    def test_character_sheet_is_what_later_pictures_send(self) -> None:
        from openrouter_client import GeneratedImage, ImageGeneration

        photo = self._png()
        linkedin_store.save_character_photo(self.table, "image/png", photo)
        frames = [self._png(color=(i * 40, i * 40, i * 40)) for i in range(1, 5)]

        def generate(prompt, aspect, seed, references, settings, n=1):
            del prompt, aspect, seed, settings
            self.assertIsNotNone(references)
            return ImageGeneration(
                images=[GeneratedImage("image/png", frame) for frame in frames[:n]],
                model="bytedance-seed/seedream-4.5",
                usage={"cost": 0.04},
            )

        drawn = linkedin_image.draw_character(self.table, generate=generate)
        self.assertEqual(drawn["candidates"], ["c1", "c2", "c3", "c4"])
        linkedin_store.choose_character(self.table, "c2")
        self.assertIsNotNone(linkedin_store.load_character_sheet())
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        linkedin_image.queue_for_post(self.table, doc["postId"], scene="The author and a huge envelope.", caption="It barely fits.", force=True)
        seen: dict[str, object] = {}

        def one(prompt, aspect, seed, references, settings, n=1):
            del prompt, aspect, seed, settings, n
            seen["references"] = references
            return ImageGeneration(images=[GeneratedImage("image/png", self._png())], model="m", usage={"cost": 0})

        linkedin_image.render_post(self.table, doc["postId"], generate=one)
        self.assertIsNotNone(seen["references"])

    def test_pending_picture_publishes_as_text(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        doc["status"] = "approved"
        doc["slotAt"] = _recent_slot()
        doc["image"] = {"status": "pending", "contentType": "image/png", "caption": "Quite a pile.", "scene": "A desk."}
        linkedin_store.put_post(self.table, doc)
        linkedin_store._IMAGE_MEMORY[doc["postId"]] = ("image/png", self._png())
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "refreshToken": "refresh-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        bodies: list[bytes] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del headers
            if url.endswith("/posts"):
                bodies.append(body or b"")
                return 201, {"x-restli-id": "urn:li:share:9"}, b""
            return 404, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true", "LINKEDIN_ENABLED": "true"}):
            linkedin.publish_one(self.table, linkedin_store.get_post(self.table, doc["postId"]))
        posted = json.loads(bodies[0])
        self.assertNotIn("content", posted)
        stored = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(stored["status"], "published")
        self.assertIn("without the picture", stored["imageNote"])

    def test_generate_image_reads_b64_and_cost(self) -> None:
        import base64

        from openrouter_client import generate_image

        payload = {
            "model": "bytedance-seed/seedream-4.5",
            "data": [{"b64_json": base64.b64encode(b"\x89PNG").decode("ascii"), "media_type": "image/png"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 1, "total_tokens": 1, "cost": 0.04},
        }
        seen: dict[str, object] = {}

        def post_json(**kwargs):
            seen["payload"] = kwargs["payload"]
            return json.dumps(payload)

        with patch("openrouter_client.post_json", side_effect=post_json):
            with patch("openrouter_client.resolve_api_key", return_value="key"):
                result = generate_image(model="bytedance-seed/seedream-4.5", prompt="a desk", secrets_client=None)
        self.assertEqual(result.images[0].data, b"\x89PNG")
        self.assertEqual(result.cost_usd, 0.04)
        self.assertEqual(seen["payload"]["resolution"], "2K")

    def test_live_generate_requests_2k(self) -> None:
        captured: dict[str, object] = {}

        def generate_image(**kwargs):
            captured.update(kwargs)
            from openrouter_client import GeneratedImage, ImageGeneration

            return ImageGeneration(images=[GeneratedImage("image/png", b"x")], model="m", usage={})

        with patch("openrouter_client.generate_image", side_effect=generate_image):
            with patch("boto3.client", return_value=object()):
                linkedin_image._live_generate("a desk", "1:1", 7, None, {}, n=1)
        self.assertEqual(captured["resolution"], "2K")
        self.assertEqual(captured["aspect_ratio"], "1:1")
        self.assertEqual(linkedin_image.IMAGE_RESOLUTION, "2K")

    def test_image_routes_redraw_and_reject_a_second_one(self) -> None:
        with patch.dict("os.environ", ENABLED):
            with patch("board_store.records_table", return_value=self.table):
                with patch("board_async.try_invoke_event", return_value=True):
                    created = lambda_handler(
                        _event("/lx-software/linkedin/posts", "POST", {"body": "A short hook.\n\nOne lesson."}),
                        None,
                    )
                    post_id = _body(created)["item"]["postId"]
                    # Creating the post already queued its picture; let that one finish first.
                    self.assertEqual(_body(created)["item"]["image"]["status"], "pending")
                    linkedin_store.put_post(
                        self.table, {**linkedin_store.get_post(self.table, post_id), "image": {"status": "failed"}}
                    )
                    first = lambda_handler(
                        _event(
                            f"/lx-software/linkedin/posts/{post_id}/image/regenerate",
                            "POST",
                            {"scene": "The author and a huge envelope.", "caption": "It barely fits."},
                        ),
                        None,
                    )
                    second = lambda_handler(
                        _event(f"/lx-software/linkedin/posts/{post_id}/image/regenerate", "POST", {}),
                        None,
                    )
        self.assertEqual(first["statusCode"], 202)
        self.assertEqual(_body(first)["item"]["image"]["status"], "pending")
        self.assertEqual(_body(first)["item"]["image"]["caption"], "It barely fits.")
        self.assertEqual(second["statusCode"], 409)

    def _generated(self, cost: float = 0.04):
        from openrouter_client import GeneratedImage, ImageGeneration

        def generate(prompt, aspect, seed, references, settings, n=1):
            del prompt, aspect, seed, references, settings
            return ImageGeneration(
                images=[GeneratedImage("image/png", self._png()) for _ in range(n)],
                model="bytedance-seed/seedream-4.5",
                usage={"cost": cost},
            )

        return generate

    def test_a_save_failure_does_not_book_spend_and_keeps_the_previous_picture(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        linkedin_store.save_post_image(self.table, doc["postId"], "image/png", self._png())
        stored = linkedin_store.get_post(self.table, doc["postId"])
        stored["image"]["caption"] = "Old line."
        linkedin_store.put_post(self.table, stored)
        with patch("board_async.try_invoke_event", return_value=True):
            queued = linkedin_image.queue_for_post(
                self.table, doc["postId"], scene="A desk.", caption="New line.", force=True
            )
        self.assertEqual(queued["image"]["status"], "pending")
        self.assertEqual(queued["image"]["held"]["caption"], "Old line.")
        with patch.object(linkedin_store, "save_post_image", side_effect=LinkedInError("The image must be under 1.5 MB.")):
            result = linkedin_image.render_post(self.table, doc["postId"], generate=self._generated())
        self.assertFalse(result["ok"])
        failed = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(failed["image"]["status"], "failed")
        self.assertEqual(failed["image"]["held"]["caption"], "Old line.")
        self.assertEqual(failed["image"]["contentType"], "image/png")
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.0)
        self.assertIn("1.5 MB", failed["image"]["error"])

    def test_parallel_pictures_cannot_each_pass_the_same_budget_check(self) -> None:
        settings = linkedin_store.default_settings()
        linkedin_store.save_settings(self.table, {**settings, "maxUsdPerMonth": 0.05})
        first = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        second = linkedin_store.create_post(self.table, {"body": "Another hook.\n\nAnother lesson."})
        with patch("board_async.try_invoke_event", return_value=True):
            linkedin_image.queue_for_post(self.table, first["postId"], scene="A desk.", caption="One.", force=True)
            linkedin_image.queue_for_post(self.table, second["postId"], scene="A desk.", caption="Two.", force=True)
        ok = linkedin_image.render_post(self.table, first["postId"], generate=self._generated(0.04))
        blocked = linkedin_image.render_post(self.table, second["postId"], generate=self._generated(0.04))
        self.assertTrue(ok["ok"])
        self.assertEqual(blocked["error"], "budget")
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.04)
        self.assertEqual(linkedin_store.get_post(self.table, second["postId"])["image"]["status"], "failed")

    def test_the_worker_reads_the_post_consistently(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        with patch("board_async.try_invoke_event", return_value=True):
            linkedin_image.queue_for_post(self.table, doc["postId"], scene="A desk.", caption="Fine.", force=True)
        reads: list[dict] = []
        original = self.table.get_item

        def spy(*args, **kwargs):
            reads.append(kwargs)
            return original(*args, **kwargs)

        self.table.get_item = spy  # type: ignore[method-assign]
        linkedin_image.render_post(self.table, doc["postId"], generate=self._generated(0))
        self.assertTrue(any(call.get("ConsistentRead") for call in reads))

    def test_a_failed_enqueue_does_not_raise_and_marks_the_picture_failed(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        with patch("board_async.try_invoke_event", side_effect=RuntimeError("invoke down")):
            stored = linkedin_image.queue_for_post(self.table, doc["postId"], scene="A desk.", caption="Fine.")
        self.assertEqual(stored["image"]["status"], "failed")
        self.assertIn("queue", stored["image"]["error"])

    def test_a_redraw_still_publishes_the_previous_picture(self) -> None:
        doc = linkedin_store.create_post(self.table, {"body": "A short hook.\n\nOne lesson."})
        linkedin_store.save_post_image(self.table, doc["postId"], "image/png", self._png())
        stored = linkedin_store.get_post(self.table, doc["postId"])
        stored["image"]["caption"] = "Old line."
        stored["status"] = "approved"
        stored["slotAt"] = _recent_slot()
        linkedin_store.put_post(self.table, stored)
        with patch("board_async.try_invoke_event", return_value=True):
            linkedin_image.queue_for_post(self.table, doc["postId"], scene="A desk.", caption="New line.", force=True)
        linkedin_store.save_connection(
            self.table,
            {
                "accessToken": "token-1",
                "refreshToken": "refresh-1",
                "tokenExpiresAt": "2099-01-01T00:00:00.000Z",
                "memberId": "member1",
                "channel": "profile",
            },
        )
        bodies: list[bytes] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None):
            del method, headers
            if url.endswith("/images?action=initializeUpload"):
                return 200, {}, b'{"value":{"uploadUrl":"https://upload.example/img","image":"urn:li:image:1"}}'
            if url == "https://upload.example/img":
                return 201, {}, b""
            if url.endswith("/posts"):
                bodies.append(body or b"")
                return 201, {"x-restli-id": "urn:li:share:11"}, b""
            return 404, {}, b""

        linkedin_api.set_transport_for_tests(transport)
        self.addCleanup(lambda: linkedin_api.set_transport_for_tests(None))
        with patch.dict("os.environ", {"LINKEDIN_PUBLISH_ENABLED": "true", "LINKEDIN_ENABLED": "true"}):
            linkedin.publish_one(self.table, linkedin_store.get_post(self.table, doc["postId"]))
        posted = json.loads(bodies[0])
        self.assertEqual(posted["content"]["media"]["altText"], "Old line.")
        published = linkedin_store.get_post(self.table, doc["postId"])
        self.assertEqual(published["status"], "published")
        self.assertFalse(published.get("imageNote"))

    def test_pictures_off_omits_the_picture_prompt_and_caption_checks(self) -> None:
        off = {**linkedin_store.default_settings(), "imagesEnabled": False}
        prompt = linkedin_draft._system_prompt(off)  # noqa: SLF001
        self.assertNotIn("Picture.", prompt)
        self.assertNotIn("imageCaption", prompt)
        self.assertNotIn("imageExpression", prompt)
        calls: list[int] = []

        def complete(messages):
            del messages
            calls.append(1)
            return {
                "body": "A short hook.\n\nOne lesson.",
                "firstComment": "",
                "hashtags": [],
                "pillar": "architecture",
                "imageCaption": "siutindei slipped in.",
            }, 0.0

        linkedin_draft.draft_one(
            settings=off,
            pillar="architecture",
            idea="",
            avoid=[],
            complete=complete,
        )
        self.assertEqual(len(calls), 1)
        calls.clear()
        linkedin_draft.draft_one(
            settings=linkedin_store.default_settings(),
            pillar="architecture",
            idea="",
            avoid=[],
            complete=complete,
        )
        self.assertEqual(calls, [1, 1])

    def test_omitting_images_enabled_keeps_the_stored_value(self) -> None:
        saved = linkedin_store.save_settings(
            self.table, {**linkedin_store.default_settings(), "imagesEnabled": False}
        )
        self.assertFalse(saved["imagesEnabled"])
        partial = {key: value for key, value in saved.items() if key != "imagesEnabled"}
        again = linkedin_store.save_settings(self.table, partial)
        self.assertFalse(again["imagesEnabled"])

    def test_candidate_ids_are_only_the_four_drawings(self) -> None:
        self.assertIsNone(linkedin_store.load_character_candidate("../sheet"))
        with self.assertRaises(LinkedInError):
            linkedin_store.choose_character(self.table, "c9")
        with patch.dict("os.environ", ENABLED):
            with patch("board_store.records_table", return_value=self.table):
                response = lambda_handler(
                    _event("/lx-software/linkedin/character/candidates/c9", "GET"),
                    None,
                )
        self.assertEqual(response["statusCode"], 400)

    def test_character_draw_stops_before_the_lambda_timeout(self) -> None:
        from openrouter_client import GeneratedImage, ImageGeneration, OpenRouterError

        linkedin_store.save_character_photo(self.table, "image/png", self._png())
        now = {"t": 0.0}
        calls: list[int] = []

        def clock() -> float:
            return now["t"]

        def generate(prompt, aspect, seed, references, settings, n=1):
            del prompt, aspect, seed, references, settings
            calls.append(n)
            now["t"] += 100
            if n > 1:
                raise OpenRouterError("slow")
            return ImageGeneration(
                images=[GeneratedImage("image/png", self._png())],
                model="m",
                usage={"cost": 0.04},
            )

        drawn = linkedin_image.draw_character(self.table, generate=generate, clock=clock)
        self.assertEqual(calls, [4, 1])
        self.assertEqual(drawn["candidates"], ["c1"])
        self.assertAlmostEqual(linkedin_store.month_spend(self.table), 0.04)

    def test_a_stuck_character_job_is_failed_on_read(self) -> None:
        job = linkedin_store.new_job(self.table, "character", {})
        job["status"] = "running"
        job["createdAt"] = "2020-01-01T00:00:00.000Z"
        linkedin_store.put_job(self.table, job)
        with patch.dict("os.environ", ENABLED):
            with patch("board_store.records_table", return_value=self.table):
                response = lambda_handler(
                    _event(f"/lx-software/linkedin/jobs/{job['jobId']}", "GET"),
                    None,
                )
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(_body(response)["job"]["status"], "failed")
        self.assertIn("timed out", _body(response)["job"]["error"])
