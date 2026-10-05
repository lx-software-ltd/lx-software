"""Real situations drafts can draw on when Ideas is empty.

A post without real material turns into generic advice. These are things this
codebase actually went through, written as the specifics a post needs: what I
noticed, what I built, what broke, where it stands. First person singular,
told in order. No company or product names; the guardrails in
``linkedin_store`` block those anyway, and ``slop_findings`` in
``linkedin_draft`` rejects a seed that slips into "we".
"""

from __future__ import annotations

from typing import Any

SEEDS: tuple[dict[str, str], ...] = (
    {
        "id": "lambda-policy-20kb",
        "pillar": "platforms",
        "text": (
            "I added one invoke permission per route on an HTTP API, plus one per EventBridge "
            "rule, because that is what the CDK constructs do by default. One morning the deploy "
            "failed with a policy-size error I had never seen. A Lambda resource-based policy is "
            "capped at 20 KB and I had filled it. I replaced the lot with one API-wide permission "
            "and moved the schedules to EventBridge Scheduler, which uses an IAM role and needs no "
            "statement on the function at all."
        ),
    },
    {
        "id": "ses-mailbox-identity",
        "pillar": "platforms",
        "text": (
            "I wrote IAM statements that listed SES identity ARNs as the resource. Every CDK "
            "assertion test passed. Production denied the first send. SES authorises "
            "SendRawEmail against the mailbox identity, not the domain ARN, so the grant that "
            "works is Resource * with a ses:FromAddress condition on the domain. My tests were "
            "testing the template, not the authoriser. I added a self-test button that sends one "
            "real email so I stop finding this out from a persona's failed approval."
        ),
    },
    {
        "id": "recursive-loop",
        "pillar": "architecture",
        "text": (
            "One Lambda function invokes itself asynchronously to run background steps: staff "
            "tasks, meeting phases, a crawler. Lambda's recursive loop detection terminated the "
            "chain after a while, silently. I set the loop setting to Allow on that single "
            "function, left Terminate on every other one, kept application caps on step counts, "
            "and replaced the dropped-invocations metric with an alarm at 250 invocations per "
            "five minutes. The alarm name is what tells my on-call persona which project it "
            "belongs to."
        ),
    },
    {
        "id": "reasoning-tokens",
        "pillar": "ai-practice",
        "text": (
            "I pointed a hybrid reasoning model at a small JSON task: write one post. It spent "
            "the entire 1,200-token budget thinking and returned a cut-off answer with no JSON, "
            "four times in a row, and I paid for each. Now I send reasoning disabled, allow "
            "2,000 tokens, retry once at 4,000 after a length cut-off, and fail the whole batch "
            "immediately with an error that names the model. Picking a non-reasoning model "
            "turned out to be the actual fix."
        ),
    },
    {
        "id": "empty-schema-example",
        "pillar": "ai-practice",
        "text": (
            "My system prompt showed the JSON schema as {\"body\":\"\"}. A JSON-mode model copied "
            "it verbatim: valid JSON, empty post, every time. I replaced the example with a filled "
            "body and the problem went away. Models imitate the example far more than they "
            "follow the sentence next to it. I now treat every example in a prompt as something "
            "the model will reproduce."
        ),
    },
    {
        "id": "voice-in-user-message",
        "pillar": "ai-practice",
        "text": (
            "I put my writing voice in the user message as a one-line hint, next to the topic. "
            "The model ignored it for weeks and I blamed the model. Moving the same text into "
            "the system prompt as its own block, saying which rules it overrides and which it "
            "does not, changed the output in the first run. Then I noticed the voice itself was "
            "a template with the placeholders still in it. Position and framing mattered more "
            "than wording; the content mattered most."
        ),
    },
    {
        "id": "ssr-window-read",
        "pillar": "architecture",
        "text": (
            "I added pre-rendering to a React marketing site for search engines. Components that "
            "read window.matchMedia during render produced different markup on the server and "
            "in the browser, and hydration quietly re-rendered the whole page. I moved every "
            "browser read behind useSyncExternalStore with a server snapshot and made the build "
            "fail on any route without an h1 or inline CSS. The site was already live when I "
            "found the first mismatch."
        ),
    },
    {
        "id": "cloudfront-extensionless",
        "pillar": "platforms",
        "text": (
            "CloudFront mapped /about to the S3 key 'about', not 'about.html'. My deploy script "
            "now uploads each pre-rendered page twice, under the extensionless key and under "
            "about/index.html, and marks .html, .txt, .xml and extensionless keys no-cache so a "
            "deploy is live without an invalidation. I spent an evening on this. The fix is three "
            "lines."
        ),
    },
    {
        "id": "four-timeouts",
        "pillar": "delivery",
        "text": (
            "PDF bank statement parsing has four timeouts that must move together: the browser "
            "polls for eight minutes, the Lambda is allowed 300 seconds, the model call 210, and "
            "a job counts as stuck at 420. I tuned each one separately at different times and "
            "the browser gave up while the job was still succeeding. They now live in one "
            "documented set and the test for one checks the others."
        ),
    },
    {
        "id": "dynamo-400kb",
        "pillar": "architecture",
        "text": (
            "I cached a government open-data CSV in DynamoDB. The first week it grew, it passed "
            "the 400 KB item limit and the nightly refresh died. The cache moved to gzip in S3 "
            "with only a pointer in DynamoDB. The limit was never the problem. The cache had no "
            "test for a large input, and I had assumed a public dataset would stay small."
        ),
    },
    {
        "id": "authorizer-cache-method",
        "pillar": "architecture",
        "text": (
            "My API Gateway authoriser caches by API key plus source IP for 60 seconds. The HTTP "
            "method is not part of the cache key, so a read-only key that fetched a GET could "
            "reuse that allow for a PUT. I moved write enforcement into the handler; the "
            "authoriser now only decides identity. Nobody exploited it. I found it reading the "
            "cache docs for an unrelated reason."
        ),
    },
    {
        "id": "one-receipt-rule-set",
        "pillar": "platforms",
        "text": (
            "SES allows one active receipt rule set per region. I had two CDK stacks each "
            "activating their own on deploy, so whichever deployed last silently took the "
            "other's inbound mail. Invoices for one business went missing for two days before I "
            "noticed. Now one stack owns the shared set and the other must not call "
            "SetActiveReceiptRuleSet."
        ),
    },
    {
        "id": "arm64-pillow",
        "pillar": "delivery",
        "text": (
            "I added Pillow to an arm64 Lambda so an AI staff member could render social cards. "
            "cdk deploy broke on the x86-64 GitHub runner: Docker bundling needs QEMU registered "
            "first. Template-only synth gets an environment variable that skips pip. The CI "
            "failure said nothing about architecture, and it took me a while to connect a font "
            "library to a CPU."
        ),
    },
    {
        "id": "naming-guard-test",
        "pillar": "leadership",
        "text": (
            "I agreed a prefix convention for CloudFormation parameters with myself and it "
            "lasted two pull requests. A Jest test now fails synth when a new parameter lacks the "
            "prefix, and an unknown key in the params file fails deploy. The convention held once "
            "it was a test instead of a note in a markdown file."
        ),
    },
    {
        "id": "invoice-date",
        "pillar": "questions",
        "text": (
            "A founder asked me why a backdated invoice showed in the wrong fiscal year. My "
            "ledger mirror dated rows by created_at. The document's invoice_date is the fact; "
            "creation time is an implementation detail. I switched the sort key and rewrote the "
            "stored rows once. It was a one-line answer and a two-hour fix."
        ),
    },
    {
        "id": "fail-closed-switch",
        "pillar": "architecture",
        "text": (
            "Every automated action in my system sits behind two switches: a stack parameter "
            "that defaults to off, and a setting that defaults to off. Unset means off. A deploy "
            "with a missing parameter does nothing rather than something. It costs a line of "
            "config per environment and it has saved me more than once, most recently when a "
            "staging stack came up with production credentials."
        ),
    },
    {
        "id": "holds-not-approvals",
        "pillar": "leadership",
        "text": (
            "I gave my AI executive board the ability to act and asked it to request my approval "
            "for every write. Within a week I was approving everything without reading it. Risky "
            "writes are now scheduled with a veto window, two to twenty-four hours depending on "
            "the class, and executed unless I object. Approvals stay only for production code "
            "and money. I read far more now that I read less."
        ),
    },
    {
        "id": "hashed-denylist",
        "pillar": "leadership",
        "text": (
            "I run a pre-commit check that blocks personal names, phone numbers and addresses "
            "from source. The denylist stores SHA-256 digests only, so the check itself does not "
            "contain the data it protects. The same check runs in CI on the whole tree. It has "
            "caught me twice, both times pasting a test fixture from real data."
        ),
    },
    {
        "id": "lighthouse-sessions",
        "pillar": "delivery",
        "text": (
            "Lighthouse CI was counting as real analytics sessions on every pull request and "
            "inflated my traffic by about a third. The numbers looked healthy; the deploy "
            "frequency gave it away. The audit now blocks the tag manager and analytics hosts. I "
            "had been quietly pleased with that traffic for a month."
        ),
    },
    {
        "id": "deploy-path-filter",
        "pillar": "delivery",
        "text": (
            "My backend deploy workflow watched only the infrastructure folder. A Lambda-only "
            "merge changed code and deployed nothing, and the bug it fixed stayed in production "
            "for a day while I assumed it was gone. The path filter now includes the Lambda "
            "source. Watch the inputs to the artifact, not the folder you think of as infra."
        ),
    },
    {
        "id": "board-mail-aliases",
        "pillar": "ai-practice",
        "text": (
            "I wanted my AI staff to read and triage customer mail, and I did not want a model "
            "provider holding customer addresses. Every mailbox is copied to one inbound address; "
            "the personas see contact#1, phone#2 aliases; I see the real addresses in the admin. "
            "Replies outside an allow-list still need my approval, and quiet hours schedule a "
            "reply for 08:00 instead of refusing it. Three months in, the masking has never been "
            "the thing that broke."
        ),
    },
    {
        "id": "dmarc-analyst",
        "pillar": "ai-practice",
        "text": (
            "I gave a security-analyst persona the DMARC aggregate reports that land in a "
            "mailbox nobody reads. A parser turns the XML into 24-hour, 7-day and 30-day "
            "summaries with no model call at all. Only a medium or high finding opens a task. "
            "Forwarding noise and unknown senders under five messages stay as information. The "
            "first useful finding was my own staging stack sending from the production domain."
        ),
    },
    {
        "id": "catalog-bisect",
        "pillar": "delivery",
        "text": (
            "I built a bulk importer that pushes approved listings to a product API in batches "
            "of 50. One batch returned HTTP 500 with no detail. I now key the failure by a hash "
            "of the batch's ids and bisect it only after a sibling batch succeeds, so I can tell "
            "one bad row from a dead server. A known-bad half is split without being posted "
            "again. The culprit was a single row with a schedule the API could not parse."
        ),
    },
    {
        "id": "one-aws-bill",
        "pillar": "questions",
        "text": (
            "Someone asked how I split one AWS invoice across three small businesses that share "
            "an account. Two cost-allocation tags, Organization and Project, on every stack, and "
            "Cost Explorer grouped by them. The AWS invoice PDF stays one total; the admin "
            "produces the tagged split and its own PDF. The rule I keep: never rotate the tag "
            "keys, because Cost Explorer orphans the history."
        ),
    },
    {
        "id": "llm-budget-meter",
        "pillar": "ai-practice",
        "text": (
            "Every model call in my admin goes through one client that books tokens and cost "
            "against a named key per application and a daily budget per board. When the budget "
            "is spent, staff tasks re-queue to tomorrow instead of failing. The hourly pull of "
            "provider usage shows the account total minus every key as 'Other', which is where "
            "my own chat usage hides. The monthly LinkedIn drafting budget is five dollars."
        ),
    },
    {
        "id": "trust-ramp",
        "pillar": "leadership",
        "text": (
            "Each AI persona has a level per tool: off, read, propose, act. Everyone starts at "
            "propose, and act is gated by an allow-list of people the system may contact and by "
            "spend caps on ads. I promote a persona one tool at a time after a run of accepted "
            "proposals, and I have demoted two. It looks like a permissions table. It behaves "
            "like probation."
        ),
    },
    {
        "id": "psd2-bank-sync",
        "pillar": "delivery",
        "text": (
            "I was typing bank balances into a spreadsheet every Sunday. Now a PSD2 aggregator "
            "links the accounts, a KMS key signs the JWTs, and a scheduler refreshes balances at "
            "05:30 every morning. The whole feature is off until one stack parameter is set, so "
            "the test environment never touches a bank. The hardest part was the consent flow, "
            "which expires every 90 days and tells nobody."
        ),
    },
    {
        "id": "statement-ocr",
        "pillar": "ai-practice",
        "text": (
            "I parse PDF bank statements with an OCR model through one provider, into statement "
            "lines with net, VAT and gross. The first version worked on my bank and failed on the "
            "second bank's layout. The fix was not a better prompt; it was returning a job id, "
            "polling, and letting a human fix the three lines the model got wrong. Accuracy is "
            "about 95 percent and the remaining five are always the same currency column."
        ),
    },
)


def seed_ids() -> set[str]:
    return {row["id"] for row in SEEDS}


def pick_seed(
    *,
    pillar: str | None,
    used: set[str],
    offset: int = 0,
) -> dict[str, Any] | None:
    """A seed not used recently, preferring the pillar. ``offset`` walks the pool."""
    pool = [row for row in SEEDS if row["id"] not in used]
    if not pool:
        pool = list(SEEDS)
    if pillar:
        matching = [row for row in pool if row["pillar"] == pillar]
        if matching:
            pool = matching
    if not pool:
        return None
    return dict(pool[offset % len(pool)])
