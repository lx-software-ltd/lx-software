import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardSeat } from "../../lib/boardModel";
import { BoardNewTaskForm } from "./BoardNewTaskForm";

const seats = [
  {
    id: "engineer-1",
    displayName: "Engineer 1",
    isActive: true,
  },
] as BoardSeat[];

describe("BoardNewTaskForm", () => {
  it("posts prNumber and issueNumber as JSON fields, not in the brief", () => {
    const onCreate = vi.fn();
    render(<BoardNewTaskForm seats={seats} disabled={false} onCreate={onCreate} />);

    fireEvent.change(screen.getByLabelText("Assignee"), { target: { value: "engineer-1" } });
    fireEvent.change(screen.getByLabelText("Deliverable"), { target: { value: "pr" } });
    fireEvent.change(screen.getByLabelText("PR #"), { target: { value: "501" } });
    fireEvent.change(screen.getByLabelText("Issue #"), { target: { value: "489" } });
    fireEvent.change(screen.getByLabelText("Brief"), {
      target: { value: "Fix the two failing resolver tests on PR #501." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));

    expect(onCreate).toHaveBeenCalledWith({
      assignee: "engineer-1",
      brief: "Fix the two failing resolver tests on PR #501.",
      deliverableType: "pr",
      slaHours: 24,
      prNumber: 501,
      issueNumber: 489,
    });
  });

  it("omits empty PR and issue fields", () => {
    const onCreate = vi.fn();
    render(<BoardNewTaskForm seats={seats} disabled={false} onCreate={onCreate} />);

    fireEvent.change(screen.getByLabelText("Brief"), { target: { value: "Write a weekly note" } });
    fireEvent.click(screen.getByRole("button", { name: "Create task" }));

    expect(onCreate).toHaveBeenCalledWith({
      assignee: "engineer-1",
      brief: "Write a weekly note",
      deliverableType: "markdown",
      slaHours: 24,
    });
  });
});
