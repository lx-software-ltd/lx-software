import { describe, expect, it } from "vitest";
import { BOARD_PERSONA_DEFAULTS } from "./contracts/generated";
import {
  approvalEditableFields,
  canRetryBoardTask,
  formatUsageCost,
  groupActionsByPriority,
  MAIL_ALLOW_LIST_ENTRY_RE,
  meetingPhaseProgress,
  memberInitials,
  memberLabel,
  mergeMemberProfile,
  parseAllowListText,
  uniqueTurnModels,
  type BoardAction,
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
