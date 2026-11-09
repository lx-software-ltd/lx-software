import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BoardToolCallList } from "./BoardToolCallList";

describe("BoardToolCallList", () => {
  it("shows a server preview under Finished the task when the row has no arguments", () => {
    render(
      <BoardToolCallList
        calls={[
          {
            callId: "call-finish",
            op: "task_finish",
            toolId: "task",
            toolLabel: "Task",
            kind: "write",
            status: "ok",
            summary: "Finished the task",
            durationMs: 4,
            deliverablePreview: '{\n  "district": "Eastern"\n}',
          },
        ]}
      />,
    );
    const item = screen.getByText("Finished the task").closest("li");
    const text = item?.textContent ?? "";
    expect(text.indexOf("Eastern")).toBeGreaterThan(text.indexOf("Finished the task"));
    expect(item?.querySelector(".board-finish-preview")).toHaveClass("bg-light", "border");
  });
});
