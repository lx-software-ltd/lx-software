"""Concrete engineering situations drafts can draw on when Ideas is empty.

A post without real material turns into generic advice. These are problems
this codebase actually solved, written as the specifics a post needs: the
system, the constraint, what was tried, what happened. No company or product
names; the guardrails in ``linkedin_store`` block those anyway.
"""

from __future__ import annotations

from typing import Any

SEEDS: tuple[dict[str, str], ...] = (
    {
        "id": "lambda-policy-20kb",
        "pillar": "platforms",
        "text": (
            "A Lambda function's resource-based policy is capped at 20 KB. Our HTTP API added "
            "one invoke permission per route, and EventBridge rules added one more each. Deploys "
            "started failing with a policy-size error nobody had seen before. The fix was one "
            "API-wide invoke permission and EventBridge Scheduler with an IAM role target, "
            "which needs no statement on the function at all."
        ),
    },
    {
        "id": "ses-mailbox-identity",
        "pillar": "platforms",
        "text": (
            "IAM statements that listed SES identity ARNs as the resource passed every CDK "
            "assertion test and were denied in production. SES authorises SendRawEmail against "
            "the mailbox identity, not the domain ARN. The working grant is Resource * with a "
            "ses:FromAddress condition on the domain. The template tests were testing the "
            "template, not the authoriser."
        ),
    },
    {
        "id": "recursive-loop",
        "pillar": "architecture",
        "text": (
            "One Lambda function invokes itself asynchronously to run background steps: staff "
            "tasks, meeting phases, a crawler. Lambda's recursive loop detection terminated the "
            "chain. We set the loop setting to Allow on that single function, left Terminate "
            "on every other one, kept application caps on step counts, and replaced the dropped "
            "RecursiveInvocationsDropped metric with an alarm at 250 invocations per five minutes."
        ),
    },
    {
        "id": "reasoning-tokens",
        "pillar": "ai-practice",
        "text": (
            "A hybrid reasoning model spent the entire 1,200-token budget thinking and returned "
            "a cut-off answer with no JSON, four times in a row. We now send reasoning disabled, "
            "allow 2,000 tokens, retry once at 4,000 after a length cut-off, and fail the whole "
            "batch immediately with an error that names the model instead of paying for every "
            "topic to fail the same way."
        ),
    },
    {
        "id": "empty-schema-example",
        "pillar": "ai-practice",
        "text": (
            "The system prompt showed the JSON schema as {\"body\":\"\"} and a JSON-mode model "
            "copied it verbatim: valid JSON, empty post. Replacing the example with a filled body "
            "fixed it. Models imitate the example far more than they follow the sentence next to "
            "it."
        ),
    },
    {
        "id": "voice-in-user-message",
        "pillar": "ai-practice",
        "text": (
            "We put the author's writing voice in the user message as a one-line hint, next to "
            "the topic. The model ignored it for weeks. Moving the same text into the system "
            "prompt as its own block, and stating which rules it overrides, changed the output "
            "immediately. Position and framing mattered more than the wording."
        ),
    },
    {
        "id": "ssr-window-read",
        "pillar": "architecture",
        "text": (
            "Pre-rendering a React site, components that read window.matchMedia during render "
            "produced different markup on the server and the client, and hydration quietly "
            "re-rendered everything. Every browser read moved behind useSyncExternalStore with a "
            "server snapshot. The build now fails on any route without an h1 or inline CSS."
        ),
    },
    {
        "id": "cloudfront-extensionless",
        "pillar": "platforms",
        "text": (
            "CloudFront mapped /about to the S3 key 'about', not 'about.html'. The deploy script "
            "uploads each pre-rendered page twice, under its extensionless key and under "
            "about/index.html, and marks .html, .txt, .xml and extensionless keys no-cache so a "
            "deploy is live without an invalidation."
        ),
    },
    {
        "id": "four-timeouts",
        "pillar": "delivery",
        "text": (
            "PDF statement parsing has four timeouts that must move together: the browser polls "
            "for eight minutes, the Lambda is allowed 300 seconds, the model call 210, and a job "
            "counts as stuck at 420. Each was tuned separately once and the browser gave up "
            "while the job was still succeeding. They are now documented as one set."
        ),
    },
    {
        "id": "dynamo-400kb",
        "pillar": "architecture",
        "text": (
            "A government open-data CSV cached in DynamoDB exceeded the 400 KB item limit the "
            "first week it grew. The cache moved to gzip in S3 with only a pointer in DynamoDB. "
            "The lesson was not the limit; it was that the cache had no test for a large input."
        ),
    },
    {
        "id": "authorizer-cache-method",
        "pillar": "architecture",
        "text": (
            "The API Gateway authoriser caches by API key plus source IP for 60 seconds. The "
            "HTTP method is not part of the cache key, so a read-only key that fetched a GET could "
            "reuse that allow for a PUT. Write enforcement moved into the handler; the authoriser "
            "only decides identity."
        ),
    },
    {
        "id": "one-receipt-rule-set",
        "pillar": "platforms",
        "text": (
            "SES allows one active receipt rule set per region. Two CDK stacks each activated "
            "their own on deploy, so whichever deployed last silently took the other's inbound "
            "mail. Now one stack owns the shared set and the other must not call "
            "SetActiveReceiptRuleSet."
        ),
    },
    {
        "id": "arm64-pillow",
        "pillar": "delivery",
        "text": (
            "Adding Pillow to an arm64 Lambda broke cdk deploy on x86-64 GitHub runners: Docker "
            "bundling needs QEMU registered first. Template-only synth gets an environment "
            "variable that skips pip. The CI failure said nothing about architecture."
        ),
    },
    {
        "id": "naming-guard-test",
        "pillar": "leadership",
        "text": (
            "We agreed a prefix convention for CloudFormation parameters and it lasted two pull "
            "requests. A Jest test now fails synth when a new parameter lacks the prefix, and an "
            "unknown key in the params file fails deploy. The convention held once it was a test "
            "instead of a review comment."
        ),
    },
    {
        "id": "invoice-date",
        "pillar": "questions",
        "text": (
            "A founder asked why a backdated invoice showed in the wrong fiscal year. The ledger "
            "mirror dated rows by created_at. The document's invoice_date is the fact; creation "
            "time is an implementation detail. We switched the sort key and rewrote stored rows "
            "once."
        ),
    },
    {
        "id": "fail-closed-switch",
        "pillar": "architecture",
        "text": (
            "Every automated action here sits behind two switches: a stack parameter that "
            "defaults to off, and a setting that defaults to off. Unset means off. A deploy with "
            "a missing parameter does nothing rather than something. It costs a line of config "
            "per environment and has saved us more than once."
        ),
    },
    {
        "id": "holds-not-approvals",
        "pillar": "leadership",
        "text": (
            "Asking a human to approve every automated write produced approval fatigue in a "
            "week. Risky writes are now scheduled with a veto window, two to twenty-four hours "
            "by class, and executed unless someone objects. Approvals stay only for production "
            "code and money."
        ),
    },
    {
        "id": "hashed-denylist",
        "pillar": "leadership",
        "text": (
            "A pre-commit check blocks personal names, phones and addresses from source. The "
            "denylist stores SHA-256 digests only, so the check itself does not contain the data "
            "it protects. The same check runs in CI on the whole tree."
        ),
    },
    {
        "id": "lighthouse-sessions",
        "pillar": "delivery",
        "text": (
            "Lighthouse CI was counting as real GA4 sessions on every pull request, inflating "
            "traffic by a third. The audit now blocks the tag manager and analytics hosts. The "
            "analytics looked fine; the deploy frequency gave it away."
        ),
    },
    {
        "id": "deploy-path-filter",
        "pillar": "delivery",
        "text": (
            "The backend deploy workflow watched only the infrastructure folder. A Lambda-only "
            "merge changed code and deployed nothing, and the bug it fixed stayed in production "
            "for a day. The path filter now includes the Lambda source. Watch the inputs to the "
            "artifact, not the folder you think of as infra."
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
