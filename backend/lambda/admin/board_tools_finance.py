"""Tool operations for the finance family."""

from __future__ import annotations

import board_finance
import board_receivables
from board_tools_core import (
    REASON_PARAM,
    ToolOp,
    _int_param,
    _obj,
    _str_param,
    _summ,
)
from contract_constants import (
    BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
)


def ops() -> list[ToolOp]:
    return [
        ToolOp(
            name="finance_cash_snapshot",
            tool_id="finance",
            kind="read",
            description=(
                "Month-end cash pack: liquid cash and credit-card totals by currency from the "
                "owner's accounts sheet (all houses, no account names), plus Siu Tin Dei "
                "statement-book income/expenditure totals. The LX Software statement book is "
                "not included. Use this for cash balance and Siu Tin Dei cash flow in the close memo."
            ),
            parameters=_obj({}),
            run=board_finance.op_cash_snapshot,
            summarize=_summ("Read cash snapshot"),
        ),
        ToolOp(
            name="finance_list_subscriptions",
            tool_id="finance",
            kind="read",
            description="Listing subscriptions from the Siu Tin Dei product database (not QuickBooks/Xero), with plan name, price and payer contact.",
            parameters=_obj({"status": _str_param("Optional status.", enum=["trial", "active", "past_due", "cancelled"])}),
            run=board_receivables.op_list_subscriptions,
            summarize=_summ("Listed subscriptions"),
        ),
        ToolOp(
            name="finance_list_invoices",
            tool_id="finance",
            kind="read",
            description="Invoices from the Siu Tin Dei product database (the book of record; there is no QuickBooks/Xero), with FPS reference, amount and status.",
            parameters=_obj({"status": _str_param("Optional status.", enum=["draft", "sent", "paid", "overdue", "void"])}),
            run=board_receivables.op_list_invoices,
            summarize=_summ("Listed invoices"),
        ),
        ToolOp(
            name="finance_aging_report",
            tool_id="finance",
            kind="read",
            description="Receivables aging from the Siu Tin Dei invoices table (the book of record; there is no QuickBooks/Xero): current / D+7 / D+21 / D+35, DSO (trailing 90-day paid revenue) and past-due by provider. An empty report is valid.",
            parameters=_obj({}),
            run=board_receivables.op_aging_report,
            summarize=_summ("Ran aging report"),
        ),
        ToolOp(
            name="finance_unit_economics",
            tool_id="finance",
            kind="read",
            description="Revenue per subscription, month-to-date CPA (AWS + Meta USD per new subscription) and gross margin at a fixed 7.8 HKD/USD; Meta from Graph month-to-date.",
            parameters=_obj({}),
            run=board_receivables.op_unit_economics,
            summarize=_summ("Read unit economics"),
            timeout_seconds=BOARD_TOOL_CALL_TIMEOUT_SLOW_SECONDS,
        ),
        ToolOp(
            name="finance_draft_invoice",
            tool_id="finance",
            kind="write",
            always_propose=True,
            description="Create a draft invoice with a unique FPS reference for a subscription.",
            parameters=_obj(
                {
                    "subscriptionId": _str_param("listing_subscriptions.id.", max_len=64),
                    "amountHkd": {"type": "number", "description": "Amount in HKD."},
                    "dueInDays": _int_param("Days until due (1-90).", maximum=90),
                    "reason": REASON_PARAM,
                },
                ["subscriptionId", "amountHkd", "reason"],
            ),
            run=board_receivables.op_draft_invoice,
            summarize=_summ("Draft invoice for {subscriptionId}"),
        ),
        ToolOp(
            name="finance_send_invoice",
            tool_id="finance",
            kind="write",
            description="Email an invoice from billing@siutindei.com. Act only for allow-listed payers.",
            parameters=_obj(
                {
                    "invoiceId": _str_param("invoices.id.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["invoiceId", "reason"],
            ),
            run=board_receivables.op_send_invoice,
            summarize=_summ("Send invoice {invoiceId}"),
            act_guard=lambda ctx, args: board_receivables.act_guard_send(ctx, args, op="finance_send_invoice"),
            preview=lambda ctx, args: board_receivables.owner_preview_send(ctx, args, op="finance_send_invoice"),
        ),
        ToolOp(
            name="finance_send_reminder",
            tool_id="finance",
            kind="write",
            description="Dunning reminder at D+7 / D+21 / D+35. Act only for allow-listed payers.",
            parameters=_obj(
                {
                    "invoiceId": _str_param("invoices.id.", max_len=64),
                    "stage": _str_param("Dunning stage; set by the nightly scheduler.", enum=["d7", "d21", "d35"]),
                    "reason": REASON_PARAM,
                },
                ["invoiceId", "reason"],
            ),
            run=board_receivables.op_send_reminder,
            summarize=_summ("Send reminder for {invoiceId}"),
            act_guard=lambda ctx, args: board_receivables.act_guard_send(ctx, args, op="finance_send_reminder"),
            preview=lambda ctx, args: board_receivables.owner_preview_send(ctx, args, op="finance_send_reminder"),
        ),
        ToolOp(
            name="finance_match_payment",
            tool_id="finance",
            kind="write",
            description="Attach a payment to an invoice. Act only when amount and FPS reference agree and the invoice is open; otherwise propose with candidate invoices.",
            parameters=_obj(
                {
                    "paymentId": _str_param("payments.id.", max_len=64),
                    "invoiceId": _str_param("invoices.id.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["paymentId", "invoiceId", "reason"],
            ),
            run=board_receivables.op_match_payment,
            summarize=_summ("Match payment {paymentId} to {invoiceId}"),
            act_guard=board_receivables.act_guard_match,
        ),
        ToolOp(
            name="finance_propose_price_change",
            tool_id="finance",
            kind="write",
            always_propose=True,
            description="Create a listing_plans row (pricing proposal). First approved plan seeds the price list.",
            parameters=_obj(
                {
                    "name": _str_param("Plan name, e.g. 'Store listing — monthly'.", max_len=80),
                    "priceHkd": {"type": "number", "description": "Price in HKD."},
                    "billingPeriod": _str_param("monthly or annual.", enum=["monthly", "annual"]),
                    "reason": REASON_PARAM,
                },
                ["name", "priceHkd", "billingPeriod", "reason"],
            ),
            run=board_receivables.op_propose_price_change,
            summarize=_summ("Propose plan {name} at ${priceHkd}"),
        ),
        ToolOp(
            name="finance_record_manual_payment",
            tool_id="finance",
            kind="write",
            always_propose=True,
            description="Record cash or cheque handed over in person (source=manual).",
            parameters=_obj(
                {
                    "amountHkd": {"type": "number", "description": "Amount in HKD."},
                    "receivedOn": _str_param("Date received YYYY-MM-DD.", max_len=10),
                    "payerName": _str_param("Who paid.", max_len=120),
                    "bankReference": _str_param("Optional FPS or cheque reference.", max_len=80),
                    "invoiceId": _str_param("Optional invoice to match.", max_len=64),
                    "reason": REASON_PARAM,
                },
                ["amountHkd", "reason"],
            ),
            run=board_receivables.op_record_manual_payment,
            summarize=_summ("Record manual payment of ${amountHkd}"),
        ),
    ]
