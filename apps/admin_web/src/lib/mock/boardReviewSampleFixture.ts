import type { BoardReviewSample } from "../boardModel";

const isoDaysAgo = (days: number): string => new Date(Date.now() - days * 86_400_000).toISOString();

/** "Sample of what ran" rows for the mock daily review: one plain mail call, one task-linked finish. */
export const boardReviewSampleFixture: BoardReviewSample[] = [
  {
    callId: "call-mail-1",
    summary: "Replied to a parent about Saturday swimming",
    op: "mail_reply",
    createdAt: isoDaysAgo(1),
    personaId: "support",
    displayName: "Support desk",
    arguments: JSON.stringify({ threadId: "t-swim", reason: "Parent asked for Saturday slots" }),
    preview: JSON.stringify({ ok: true, messageId: "m-swim" }),
    task: null,
  },
  {
    callId: "call-finish-1",
    summary: "Finished the task",
    op: "task_finish",
    createdAt: isoDaysAgo(1),
    personaId: "provider-success",
    displayName: "Provider success",
    seatId: "provider-success",
    taskId: "task-review",
    arguments: JSON.stringify({ status: "review", deliverable: "Two warm threads summarised." }),
    preview: JSON.stringify({ ok: true, status: "review" }),
    task: {
      taskId: "task-review",
      assignee: "provider-success",
      status: "review",
      brief: "Summarise the two warm provider threads.",
      summary: "Both providers asked for the onboarding link.",
    },
  },
];
