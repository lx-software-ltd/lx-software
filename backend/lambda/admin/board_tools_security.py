"""Tool operations for the security family."""

from __future__ import annotations

import board_dmarc
import board_security
from board_tools_core import (
    REASON_PARAM,
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)


def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="security_github_alerts",
            tool_id="security",
            kind="read",
            description="Open Dependabot, code-scanning and secret-scanning alerts on the siutindei repo (cached hourly).",
            parameters=_obj({"limit": _int_param("Max alerts per type (1-50).", maximum=50)}),
            run=board_security.op_github_alerts,
            summarize=_summ("Listed GitHub security alerts"),
        ),
        ToolOp(
            name="security_aws_findings",
            tool_id="security",
            kind="read",
            description="Active HIGH/CRITICAL Security Hub findings and IAM Access Analyzer findings (cached hourly).",
            parameters=_obj({}),
            run=board_security.op_hub_findings,
            summarize=_summ("Listed AWS security findings"),
        ),
        ToolOp(
            name="security_cognito",
            tool_id="security",
            kind="read",
            description="Cognito user-pool MFA, tier, threat-protection mode, password policy, and 24h CloudWatch sign-in throttles/successes. Failed sign-ins are not measured; no user listing.",
            parameters=_obj({}),
            run=board_security.op_cognito,
            summarize=_summ("Read Cognito security posture"),
        ),
        ToolOp(
            name="security_dmarc_summary",
            tool_id="security",
            kind="read",
            description=(
                "DMARC aggregate summary for the last 24 hours, 7 days and 30 days: "
                "aligned percent, reporting orgs, per-source results and findings. Reads the hourly cache and does not recompute it."
            ),
            parameters=_obj({}),
            run=board_dmarc.op_summary,
            summarize=_summ("Read DMARC aggregate summary"),
        ),
        ToolOp(
            name="security_open_remediation",
            tool_id="security",
            kind="write",
            always_propose=True,
            description="Open a GitHub issue describing a finding and the fix. Always a proposal until the founder approves.",
            parameters=_obj(
                {
                    "title": _str_param("Issue title.", max_len=200),
                    "body": _str_param("Markdown: finding, impact, proposed fix.", max_len=4000),
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels; 'security' is added if missing."},
                    "reason": REASON_PARAM,
                },
                ["title", "body", "reason"],
            ),
            run=board_security.op_open_remediation,
            summarize=_summ("Propose security issue: {title}"),
        ),
    ]
