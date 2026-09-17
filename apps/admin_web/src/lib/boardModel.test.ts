import { describe, expect, it } from "vitest";
import { BOARD_PERSONA_DEFAULTS } from "./contracts/generated";
import {
  approvalEditableFields,
  boardTaskHref,
  boardTaskSearchParams,
  canRetryBoardTask,
  showTaskReviewActions,
  catalogDrawerMessageForTask,
  catalogMutationErrorForTask,
  filterBoardTasks,
  liveCatalogPreviewForTask,
  formatRelativeDuration,
  formatRelativeTime,
  formatUsageCost,
  groupActionsByPriority,
  groupTasksByLane,
  MAIL_ALLOW_LIST_ENTRY_RE,
  meetingPhaseProgress,
  memberInitials,
  memberLabel,
  mergeMemberProfile,
  parseAllowListText,
  readBoardTaskIdFromSearch,
  shortTaskId,
  taskActorLabel,
  taskSlaLabel,
  taskLane,
  taskSlaState,
  taskStatusLabel,
  taskStatusTone,
  uniqueTurnModels,
  type BoardAction,
  type BoardTask,
} from "./boardModel";

const cto = BOARD_PERSONA_DEFAULTS.find((p) => p.id === "cto")!;

function action(overrides: Partial<BoardAction>): BoardAction {
  return {
    actionId: "a",
    title: "t",
    detail: "",
    persona: "ceo",
    priority: "next",
    effort: "M",
    metric: "",
    dependsOn: [],
    status: "open",
    note: "",
    meetingId: "m",
    reaffirmedByMeetingIds: [],
    dueAt: null,
    createdAt: "2026-09-01T00:00:00.000Z",
    updatedAt: "2026-09-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("mergeMemberProfile", () => {
  it("uses contract defaults when there is no override", () => {
    const profile = mergeMemberProfile(cto, null);
    expect(profile.mandate).toBe(cto.mandate);
    expect(profile.displayName).toBe("CTO");
    expect(profile.isOverridden.mandate).toBe(false);
  });

  it("applies non-blank overrides only", () => {
    const profile = mergeMemberProfile(cto, {
      mandate: "  Ship Flutter first.  ",
      vision: "   ",
      displayName: "Ada",
    });
    expect(profile.mandate).toBe("Ship Flutter first.");
    expect(profile.vision).toBe(cto.vision);
    expect(profile.displayName).toBe("Ada");
    expect(profile.isOverridden).toEqual({
      vision: false,
      mission: false,
      mandate: true,
      displayName: true,
    });
  });
});

describe("groupActionsByPriority", () => {
  it("groups and sorts by due date then creation", () => {
    const grouped = groupActionsByPriority([
      action({ actionId: "1", priority: "now", dueAt: "2026-09-10T00:00:00.000Z" }),
      action({ actionId: "2", priority: "now", dueAt: "2026-09-05T00:00:00.000Z" }),
      action({ actionId: "3", priority: "later" }),
      action({ actionId: "4", priority: "bogus" as BoardAction["priority"] }),
    ]);
    expect(grouped.now.map((a) => a.actionId)).toEqual(["2", "1"]);
    expect(grouped.next).toEqual([]);
    expect(grouped.later.map((a) => a.actionId)).toEqual(["3", "4"]);
  });
});

describe("meetingPhaseProgress", () => {
  it("reports the running phase position", () => {
    const progress = meetingPhaseProgress({
      status: "running",
      phase: "positions",
      phases: ["prepare", "agenda", "positions", "synthesis", "persist"],
    });
    expect(progress.index).toBe(2);
    expect(progress.total).toBe(5);
    expect(progress.percent).toBe(50);
    expect(progress.label).toBe("Members give positions");
  });

  it("is complete for finished meetings", () => {
    const progress = meetingPhaseProgress({ status: "succeeded", phase: "done", phases: ["a", "b"] });
    expect(progress.percent).toBe(100);
    expect(progress.label).toBe("Done");
  });
});

describe("allow-list parsing", () => {
  it("accepts emails, domains, and E.164 phones", () => {
    expect(MAIL_ALLOW_LIST_ENTRY_RE.test("coach@swimhk.example")).toBe(true);
    expect(MAIL_ALLOW_LIST_ENTRY_RE.test("@vendor.example")).toBe(true);
    expect(MAIL_ALLOW_LIST_ENTRY_RE.test("+85291234567")).toBe(true);
    expect(MAIL_ALLOW_LIST_ENTRY_RE.test("85291234567")).toBe(true);
    expect(MAIL_ALLOW_LIST_ENTRY_RE.test("not-an-address")).toBe(false);
    expect(parseAllowListText("Coach@SwimHK.example\n+852 9123 4567")).toEqual([
      "coach@swimhk.example",
      "+85291234567",
    ]);
  });
});

describe("approvalEditableFields", () => {
  const preview = {
    kind: "email" as const,
    from: "hello@siutindei.com",
    to: ["parent@example.com"],
    cc: [],
    subject: "Class on Saturday",
    text: "Hello Wendy, see you Saturday",
    threadId: "t1",
    sendEnabled: true,
  };

  it("offers only the body for a reply (subject comes from the thread)", () => {
    const fields = approvalEditableFields({ threadId: "t1", body: "Hello contact#3, see you Saturday", reason: "Reply" }, preview);
    expect(fields.map((f) => f.key)).toEqual(["body"]);
    expect(fields[0].value).toBe("Hello Wendy, see you Saturday");
  });

  it("offers subject and body for a new email", () => {
    const fields = approvalEditableFields(
      { fromMailbox: "hello", to: ["parent@example.com"], subject: "Class on Saturday", body: "Hello", reason: "New" },
      preview,
    );
    expect(fields.map((f) => f.key)).toEqual(["subject", "body"]);
    expect(fields[0].value).toBe("Class on Saturday");
  });

  it("exposes message text for Meta writes", () => {
    const fields = approvalEditableFields({ message: "Boost this", reason: "Launch" });
    expect(fields).toEqual([{ key: "message", label: "Message", multiline: true, value: "Boost this" }]);
  });
});

describe("formatting helpers", () => {
  it("formats costs", () => {
    expect(formatUsageCost(0)).toBe("USD 0.00");
    expect(formatUsageCost(0.0042)).toBe("USD 0.0042");
    expect(formatUsageCost(1.234)).toBe("USD 1.23");
  });

  it("lists unique served models from transcript turns", () => {
    expect(
      uniqueTurnModels([
        { seq: 1, phase: "agenda", personaId: "ceo", displayName: "CEO", title: "CEO", text: "a", createdAt: "t", model: "deepseek/deepseek-chat" },
        { seq: 2, phase: "positions", personaId: "cfo", displayName: "CFO", title: "CFO", text: "b", createdAt: "t", model: " openai/gpt-4.1-mini " },
        { seq: 3, phase: "positions", personaId: "cto", displayName: "CTO", title: "CTO", text: "c", createdAt: "t", model: "openai/gpt-4.1-mini" },
        { seq: 4, phase: "positions", personaId: "coo", displayName: "COO", title: "COO", text: "d", createdAt: "t", kind: "tool" },
      ]),
    ).toEqual(["deepseek/deepseek-chat", "openai/gpt-4.1-mini"]);
  });

  it("derives initials and labels", () => {
    expect(memberInitials({ displayName: "CTO", shortName: "CTO" })).toBe("CTO");
    expect(memberInitials({ displayName: "Ada Lovelace", shortName: "CTO" })).toBe("AL");
    const members = [{ id: "cto", displayName: "Ada", shortName: "CTO" }];
    expect(memberLabel(members, "cto")).toBe("Ada (CTO)");
    expect(memberLabel(members, "cfo")).toBe("CFO");
  });
});

describe("canRetryBoardTask", () => {
  it("allows retry from failed and needs_owner only", () => {
    expect(canRetryBoardTask("failed")).toBe(true);
    expect(canRetryBoardTask("needs_owner")).toBe(true);
    expect(canRetryBoardTask("review")).toBe(false);
    expect(canRetryBoardTask("delivered")).toBe(false);
    expect(canRetryBoardTask("waiting_subtask")).toBe(false);
  });
});

function task(overrides: Partial<BoardTask>): BoardTask {
  return {
    taskId: "abcdef0123456789",
    status: "queued",
    assignee: "support",
    assigneeKind: "seat",
    managerId: "coo",
    origin: "owner",
    brief: "Draft a reply",
    deliverableType: "markdown",
    budgetUsd: 1,
    slaAt: "2026-09-16T00:00:00Z",
    step: 1,
    stepsUsed: 1,
    revisions: 0,
    usage: { promptTokens: 10, completionTokens: 4, cost: 0.02, calls: 1 },
    summary: "",
    evidence: [],
    openQuestions: [],
    confidence: "",
    reviews: 0,
    lastReview: null,
    createdAt: "2026-09-14T00:00:00Z",
    updatedAt: "2026-09-14T12:00:00Z",
    ...overrides,
  };
}

describe("task dashboard helpers", () => {
  it("shortens task ids to eight characters", () => {
    expect(shortTaskId("abcdef0123456789")).toBe("abcdef01");
    expect(shortTaskId("short")).toBe("short");
  });

  it("maps statuses onto lanes and tones", () => {
    expect(taskLane("needs_owner")).toBe("attention");
    expect(taskLane("review")).toBe("attention");
    expect(taskLane("running")).toBe("in_progress");
    expect(taskLane("waiting_subtask")).toBe("in_progress");
    expect(taskLane("queued")).toBe("queued");
    expect(taskLane("awaiting_import")).toBe("to_import");
    expect(taskLane("failed")).toBe("done");
    expect(taskLane("delivered")).toBe("done");
    expect(taskStatusLabel("awaiting_import")).toBe("To import");
    expect(taskStatusTone("failed")).toBe("danger");
    expect(taskStatusLabel("waiting_subtask")).toBe("Waiting help");
  });

  it("classifies SLA and formats relative time", () => {
    const now = Date.parse("2026-09-15T12:00:00Z");
    expect(taskSlaState("2026-09-15T10:00:00Z", now)).toBe("overdue");
    expect(taskSlaState("2026-09-15T16:00:00Z", now)).toBe("soon");
    expect(taskSlaState("2026-09-16T12:00:00Z", now)).toBe("ok");
    expect(formatRelativeTime("2026-09-15T10:00:00Z", now)).toBe("2h ago");
    expect(formatRelativeTime("2026-09-15T18:00:00Z", now)).toBe("in 6h");
    expect(formatRelativeDuration("2026-09-15T10:00:00Z", now)).toBe("2h");
    expect(taskSlaLabel("2026-09-15T10:00:00Z", now)).toBe("Overdue 2h");
    expect(taskSlaLabel("2026-09-16T12:00:00Z", now)).toBe("SLA in 1d");
    expect(taskSlaState("2026-09-15T10:00:00Z", now, "awaiting_import")).toBe("none");
    expect(showTaskReviewActions({ status: "review" })).toBe(true);
    expect(
      showTaskReviewActions({
        status: "needs_owner",
        importPhase: "collision",
        eventRef: { kind: "catalog-micro-batch" },
      }),
    ).toBe(false);
    expect(showTaskReviewActions({ status: "needs_owner" })).toBe(true);
  });

  it("resolves seat and persona labels", () => {
    expect(taskActorLabel("support", [{ id: "support", displayName: "Parent Support" }])).toBe("Parent Support");
    expect(taskActorLabel("cfo")).toBe("CFO");
    expect(taskActorLabel("unknown-seat")).toBe("unknown-seat");
  });

  it("filters by query, assignee, status, and finished visibility", () => {
    const rows = [
      task({ taskId: "task-owner-aa", status: "needs_owner", brief: "Reconcile payments", assignee: "accountant" }),
      task({ taskId: "task-done-bb", status: "delivered", brief: "Month-end snapshot", assignee: "cfo" }),
      task({ taskId: "task-mail-cc", status: "queued", brief: "Reply to parent", assignee: "support" }),
    ];
    expect(filterBoardTasks(rows).map((t) => t.taskId)).toEqual(["task-owner-aa", "task-mail-cc"]);
    expect(filterBoardTasks(rows, { includeFinished: true, status: "delivered" }).map((t) => t.taskId)).toEqual([
      "task-done-bb",
    ]);
    expect(filterBoardTasks(rows, { query: "task-own" }).map((t) => t.taskId)).toEqual(["task-owner-aa"]);
    expect(filterBoardTasks(rows, { query: "parent support" }).map((t) => t.taskId)).toEqual(["task-mail-cc"]);
    expect(filterBoardTasks(rows, { assignee: "cfo", includeFinished: true }).map((t) => t.taskId)).toEqual([
      "task-done-bb",
    ]);
  });

  it("groups lanes with attention and failed first", () => {
    const grouped = groupTasksByLane([
      task({ taskId: "r", status: "review", updatedAt: "2026-09-14T18:00:00Z" }),
      task({ taskId: "o", status: "needs_owner", updatedAt: "2026-09-14T10:00:00Z" }),
      task({ taskId: "d", status: "delivered", finishedAt: "2026-09-14T18:00:00Z" }),
      task({ taskId: "f", status: "failed", updatedAt: "2026-09-14T11:00:00Z" }),
    ]);
    expect(grouped.attention.map((t) => t.taskId)).toEqual(["o", "r"]);
    expect(grouped.done.map((t) => t.taskId)).toEqual(["f", "d"]);
  });

  it("scopes live catalog preview and errors to the open task", () => {
    const live = { ok: true, taskId: "task-a", district: "Eastern" };
    const fallback = { ok: true, taskId: "task-b", district: "Wan Chai" };
    expect(liveCatalogPreviewForTask(live, "task-a", fallback)).toEqual(live);
    expect(liveCatalogPreviewForTask(live, "task-b", fallback)).toEqual(fallback);
    expect(liveCatalogPreviewForTask(undefined, "task-a", fallback)).toEqual(fallback);
    expect(catalogMutationErrorForTask("task-a", "task-a", new Error("off"), (err) => (err instanceof Error ? err.message : null))).toBe(
      "off",
    );
    expect(catalogMutationErrorForTask("task-a", "task-b", new Error("off"), (err) => (err instanceof Error ? err.message : null))).toBeNull();
    expect(
      catalogDrawerMessageForTask(
        "task-a",
        [
          { variables: { taskId: "task-a" }, error: new Error("skip failed") },
          { variables: "task-a", error: new Error("preview failed") },
        ],
        (err) => (err instanceof Error ? err.message : null),
      ),
    ).toBe("skip failed");
    expect(
      catalogDrawerMessageForTask("task-b", [{ variables: "task-a", error: new Error("preview failed") }], (err) =>
        err instanceof Error ? err.message : null,
      ),
    ).toBeNull();
  });

  it("builds a shareable task deep link", () => {
    expect(readBoardTaskIdFromSearch("?tab=dashboard&task=abc123")).toBe("abc123");
    expect(readBoardTaskIdFromSearch("?section=tasks")).toBeNull();
    expect(boardTaskHref("abc123", "?tab=dashboard")).toBe("?tab=board&section=tasks&task=abc123");
    expect(boardTaskSearchParams(null, "?tab=board&section=tasks&task=abc123").get("task")).toBeNull();
    expect(boardTaskSearchParams(null, "?tab=dashboard").get("section")).toBeNull();
    expect(boardTaskSearchParams(null, "?tab=dashboard").get("tab")).toBe("dashboard");
  });
});
