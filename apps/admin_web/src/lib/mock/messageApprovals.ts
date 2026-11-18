import type { BoardApproval } from "../boardModel";

const CREATED_AT = "2026-11-18T09:30:00.000Z";

function metaApproval(approvalId: string, op: string, summary: string, args: Record<string, unknown>, preview: Record<string, unknown>): BoardApproval {
  return {
    approvalId,
    status: "pending",
    personaId: "cmo",
    displayName: "Maya",
    toolId: "meta",
    toolLabel: "Meta",
    op,
    kind: "write",
    arguments: args,
    summary,
    reason: "Needs the owner's approval",
    context: { kind: "task", taskId: "task-messages" },
    createdAt: CREATED_AT,
    updatedAt: CREATED_AT,
    preview: { kind: "meta", cc: [], threadId: "", sendEnabled: true, ...preview },
  } as unknown as BoardApproval;
}

/** One approval with no recipient (argument table) and one reply (message card). */
export const messageApprovalsFixture: BoardApproval[] = [
  metaApproval(
    "appr-ad-set",
    "meta_create_ad_set",
    "Create an ad set for Stanley parents",
    { campaignId: "120000000000001", name: "Stanley parents", dailyBudgetUsd: 15, countries: ["HK"] },
    { from: "facebook", to: [], subject: "Stanley parents", text: "" },
  ),
  metaApproval(
    "appr-wa-reply",
    "meta_reply_whatsapp",
    "Reply to Harbour Club on WhatsApp",
    { threadId: "thread-harbour", message: "Thanks, Saturday 9am is noted." },
    {
      from: "whatsapp",
      to: ["+85255500100"],
      subject: "meta_reply_whatsapp",
      text: "Thanks, Saturday 9am is noted.",
      threadId: "thread-harbour",
      phoneLink: "https://wa.me/85255500100?text=Thanks%2C%20Saturday%209am%20is%20noted.",
    },
  ),
];
