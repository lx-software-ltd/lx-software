import { describe, expect, it } from "vitest";
import { tasksNeedPolling, type BoardTask } from "../lib/boardModel";

function task(status: BoardTask["status"]): BoardTask {
  return {
    taskId: `t-${status}`,
    status,
    assignee: "cfo",
    assigneeKind: "persona",
    managerId: "cfo",
    origin: "owner",
    brief: "Check costs",
    deliverableType: "markdown",
    budgetUsd: 1,
    slaAt: "2026-09-11T00:00:00Z",
    step: 0,
    stepsUsed: 0,
    revisions: 0,
    usage: { promptTokens: 0, completionTokens: 0, cost: 0, calls: 0 },
    summary: "",
    evidence: [],
    openQuestions: [],
    confidence: "",
    reviews: 0,
    createdAt: "2026-09-10T00:00:00Z",
    updatedAt: "2026-09-10T00:00:00Z",
  };
}

describe("tasksNeedPolling", () => {
  it("polls while any task is running or in review", () => {
    expect(tasksNeedPolling([task("queued"), task("delivered")])).toBe(false);
    expect(tasksNeedPolling([task("running")])).toBe(true);
    expect(tasksNeedPolling([task("review"), task("delivered")])).toBe(true);
    expect(tasksNeedPolling([])).toBe(false);
  });
});
