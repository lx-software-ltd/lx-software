import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { boardOverviewFixture, boardToolsFixture } from "../../lib/mock/fixtures";
import type { BoardToolCallLogEntry } from "../../lib/boardModel";
import { BoardToolsCard } from "./BoardToolsCard";

const finishCall: BoardToolCallLogEntry = {
  callId: "call-finish",
  op: "task_finish",
  toolId: "task",
  toolLabel: "Task",
  kind: "write",
  status: "ok",
  summary: "Finished the task",
  durationMs: 12,
  personaId: "content-marketer",
  displayName: "Mei",
  actor: "persona",
  level: "act",
  arguments: {
    deliverableType: "json",
    deliverable: JSON.stringify({ district: "Eastern", organisations: [{ name_en: "Quarry Bay Park" }] }),
  },
  resultPreview: JSON.stringify({ ok: true, deliverableKey: "board/executive/staff/t/deliverable.json" }),
  context: { kind: "task" },
  createdAt: "2026-11-08T01:30:00Z",
};

describe("BoardToolsCard finish preview", () => {
  it("shows the JSON under Finished the task and keeps the result key", () => {
    render(
      <BoardToolsCard
        payload={boardToolsFixture}
        members={boardOverviewFixture.members}
        isSaving={false}
        onSave={vi.fn()}
        callLog={[finishCall]}
        isCallLogLoading={false}
        showCallLog
        onToggleCallLog={vi.fn()}
      />,
    );
    const item = screen.getByText("Finished the task").closest(".list-group-item");
    const preview = item?.querySelector(".board-finish-preview");
    expect(preview).toHaveTextContent("Quarry Bay Park");
    const text = item?.textContent ?? "";
    expect(text.indexOf("Quarry Bay Park")).toBeGreaterThan(text.indexOf("Finished the task"));
    expect(item?.querySelector("details")).toHaveTextContent("deliverableKey");
  });
});
