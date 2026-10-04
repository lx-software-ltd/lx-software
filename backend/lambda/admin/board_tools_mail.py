"""Tool operations for the mail family."""

from __future__ import annotations

from typing import Any

import board_mail
from board_tools_core import (
    REASON_PARAM,
    ToolOp,
    _int_param,
    _obj,
    _reply_guard,
    _short,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_MAIL_BODY_MAX_CHARS,
    BOARD_MAIL_SUBJECT_MAX_LEN,
)


def _summ_mail_list(args: dict[str, Any]) -> str:
    parts = ["Listed email threads"]
    if args.get("mailbox"):
        parts.append(f"in {_short(args['mailbox'], 40)}")
    if args.get("query"):
        parts.append(f"matching '{_short(args['query'], 40)}'")
    if args.get("unreadOnly"):
        parts.append("(unread only)")
    return " ".join(parts)

def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="mail_list_mailboxes",
            tool_id="mail",
            kind="read",
            description="List the company mailboxes (hello@, billing@, ...) with thread and unread counts.",
            parameters=_obj({}),
            run=board_mail.op_list_mailboxes,
            summarize=_summ("Listed mailboxes"),
        ),
        ToolOp(
            name="mail_list_threads",
            tool_id="mail",
            kind="read",
            description=(
                "List email threads, newest first, optionally for one mailbox, matching keywords, or unread only. "
                "Contacts appear as stable aliases like contact#12; never guess real names or addresses. "
                "hasAttachments only signals files are present; PDF contents are not readable."
            ),
            parameters=_obj(
                {
                    "mailbox": _str_param("Optional mailbox (local part or full address).", max_len=120),
                    "query": _str_param("Optional keywords; all must match subject, snippet or sender.", max_len=200),
                    "unreadOnly": {"type": "boolean", "description": "Only threads the founder has not read yet."},
                    "limit": _int_param("Max threads (1-30).", maximum=30),
                }
            ),
            run=board_mail.op_list_threads,
            summarize=_summ_mail_list,
        ),
        ToolOp(
            name="mail_get_thread",
            tool_id="mail",
            kind="read",
            description=(
                "Read every message in one thread (bodies, text attachments and attachment names; contacts pseudonymised). "
                "PDF attachment text is NOT extracted: such files are listed under attachmentsSkipped, so ask the founder for anything inside a PDF."
            ),
            parameters=_obj({"threadId": _str_param("Thread id from mail_list_threads.", max_len=64)}, ["threadId"]),
            run=board_mail.op_get_thread,
            summarize=_summ("Read email thread {threadId}"),
        ),
        ToolOp(
            name="mail_contact_history",
            tool_id="mail",
            kind="read",
            description="List the threads a contact alias (e.g. contact#12) has taken part in.",
            parameters=_obj({"contact": _str_param("Contact alias exactly as shown in a thread.", max_len=40)}, ["contact"]),
            run=board_mail.op_contact_history,
            summarize=_summ("Looked up history for {contact}"),
        ),
        ToolOp(
            name="mail_reply",
            tool_id="mail",
            kind="write",
            description=(
                "Reply to the last inbound message of a thread from the mailbox it was sent to. "
                "Plain text only; write as the company, sign off as 'The siutindei team'."
            ),
            parameters=_obj(
                {
                    "threadId": _str_param("Thread id from mail_list_threads.", max_len=64),
                    "body": _str_param("Plain-text reply body.", max_len=BOARD_MAIL_BODY_MAX_CHARS),
                    "templateId": _str_param("Optional approved template id.", max_len=80),
                    "reason": REASON_PARAM,
                },
                ["threadId", "body", "reason"],
            ),
            run=board_mail._op_write("mail_reply"),
            summarize=_summ("Reply in email thread {threadId}"),
            act_guard=_reply_guard(
                "mail_reply",
                lambda ctx, args: board_mail.act_guard(ctx, args, op="mail_reply"),
            ),
            validate=lambda ctx, args: board_mail.validate_outgoing(ctx, args, op="mail_reply"),
            preview=lambda ctx, args: board_mail.owner_preview(ctx, args, op="mail_reply"),
        ),
        ToolOp(
            name="mail_send",
            tool_id="mail",
            kind="write",
            description="Start a new email from a company mailbox to one or more contacts (aliases or full addresses).",
            parameters=_obj(
                {
                    "fromMailbox": _str_param("Sending mailbox, e.g. hello or billing@siutindei.com.", max_len=120),
                    "to": {"type": "array", "items": {"type": "string"}, "description": "Recipients: contact aliases or addresses."},
                    "subject": _str_param("Subject line.", max_len=BOARD_MAIL_SUBJECT_MAX_LEN),
                    "body": _str_param("Plain-text body.", max_len=BOARD_MAIL_BODY_MAX_CHARS),
                    "reason": REASON_PARAM,
                },
                ["fromMailbox", "to", "subject", "body", "reason"],
            ),
            run=board_mail._op_write("mail_send"),
            summarize=_summ("Send email: {subject}"),
            act_guard=lambda ctx, args: board_mail.act_guard(ctx, args, op="mail_send"),
            validate=lambda ctx, args: board_mail.validate_outgoing(ctx, args, op="mail_send"),
            preview=lambda ctx, args: board_mail.owner_preview(ctx, args, op="mail_send"),
        ),
        ToolOp(
            name="mail_forward",
            tool_id="mail",
            kind="write",
            description="Forward the latest message of a thread to a provider or vendor with a short note.",
            parameters=_obj(
                {
                    "threadId": _str_param("Thread id from mail_list_threads.", max_len=64),
                    "to": {"type": "array", "items": {"type": "string"}, "description": "Recipients: contact aliases or addresses."},
                    "note": _str_param("Short note placed above the forwarded message.", max_len=2000),
                    "reason": REASON_PARAM,
                },
                ["threadId", "to", "reason"],
            ),
            run=board_mail._op_write("mail_forward"),
            summarize=_summ("Forward email thread {threadId}"),
            act_guard=lambda ctx, args: board_mail.act_guard(ctx, args, op="mail_forward"),
            validate=lambda ctx, args: board_mail.validate_outgoing(ctx, args, op="mail_forward"),
            preview=lambda ctx, args: board_mail.owner_preview(ctx, args, op="mail_forward"),
        ),
        ToolOp(
            name="mail_report_phishing",
            tool_id="mail",
            kind="write",
            description=(
                "Flag a mailbox thread as suspected phishing for the founder. Always queued to Approvals; "
                "available to every role that can read mail, including the CISO."
            ),
            parameters=_obj(
                {
                    "threadId": _str_param("Thread id from mail_list_threads.", max_len=64),
                    "note": _str_param("Why this looks like phishing.", max_len=800),
                    "reason": REASON_PARAM,
                },
                ["threadId", "reason"],
            ),
            run=board_mail.op_report_phishing,
            summarize=_summ("Report phishing on thread {threadId}"),
            level_floor="read",
            always_propose=True,
            preview=board_mail.owner_preview_phishing,
        ),
    ]
