import type { BoardReviewSample, BoardToolCallLogEntry } from "../boardModel";

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
    arguments: JSON.stringify({
      status: "review",
      deliverableType: "json",
      deliverable: JSON.stringify({
        district: "Eastern",
        organisations: [{ name_en: "Quarry Bay Park Playground", type: "playground" }],
      }),
    }),
    deliverablePreview: JSON.stringify(
      {
        district: "Eastern",
        organisations: [{ name_en: "Quarry Bay Park Playground", type: "playground" }],
      },
      null,
      2,
    ),
    preview: JSON.stringify({ ok: true, status: "review", deliverableKey: "board/executive/staff/task-review/deliverable.json" }),
    task: {
      taskId: "task-review",
      assignee: "provider-success",
      status: "review",
      brief: "Summarise the two warm provider threads.",
      summary: "Both providers asked for the onboarding link.",
    },
  },
];

/** One finished task in the mock tool-call log, so the JSON preview is visible without AWS. */
export const boardToolCallsFixture: BoardToolCallLogEntry[] = [
  {
    callId: "call-finish-1",
    op: "task_finish",
    toolId: "task",
    toolLabel: "Task",
    kind: "write",
    status: "ok",
    summary: "Finished the task",
    durationMs: 840,
    personaId: "provider-success",
    displayName: "Provider success",
    actor: "persona",
    level: "act",
    arguments: {
      status: "review",
      deliverableType: "json",
      deliverable: JSON.stringify({
        district: "Eastern",
        organisations: [{ name_en: "Quarry Bay Park Playground", type: "playground" }],
      }),
    },
    resultPreview: JSON.stringify({
      ok: true,
      status: "review",
      deliverableKey: "board/executive/staff/task-review/deliverable.json",
    }),
    context: { kind: "task" },
    createdAt: isoDaysAgo(1),
  },
];
