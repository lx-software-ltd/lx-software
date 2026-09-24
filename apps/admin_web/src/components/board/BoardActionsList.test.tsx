import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardAction, BoardSeat } from "../../lib/boardModel";
import { BoardActionsList } from "./BoardActionsList";

function action(overrides: Partial<BoardAction> = {}): BoardAction {
  return {
    actionId: "a1",
    title: "Call 10 activity providers",
    detail: "Book calls with providers in Sha Tin.",
    persona: "coo",
    priority: "now",
    effort: "M",
    metric: "10 calls booked",
    dependsOn: [],
    status: "open",
    note: "",
    meetingId: "m1",
    reaffirmedByMeetingIds: [],
    dueAt: null,
    createdAt: "2026-09-12T00:00:00Z",
    updatedAt: "2026-09-12T00:00:00Z",
    ...overrides,
  };
}

const prospector: BoardSeat = {
  id: "prospector",
  reportsTo: "cmo",
  title: "Prospector",
  modelTier: "desk",
  isActive: true,
  isActiveDefault: false,
  tools: {},
  brief: "Find venues.",
  displayName: "Priya",
  defaults: { brief: "Find venues.", displayName: "Prospector", modelTier: "desk" },
  isOverridden: { brief: false, displayName: true, isActive: true, modelTier: false },
  effectiveLevels: {},
};

const baseProps = {
  members: [],
  isLoading: false,
  onUpdate: vi.fn(),
  onOpenMeeting: vi.fn(),
};

describe("BoardActionsList ids", () => {
  it("shows the action id with the other row fields", () => {
    render(<BoardActionsList {...baseProps} actions={[action()]} />);
    expect(screen.getByLabelText("Action a1")).toHaveTextContent("a1");
    expect(screen.getByText("Call 10 activity providers")).toBeInTheDocument();
    expect(screen.getByText("M")).toBeInTheDocument();
    expect(screen.getByText("10 calls booked")).toBeInTheDocument();
  });

  it("shows the full action id rather than a shortened prefix", () => {
    const actionId = "a1b2c3d4e5f6789012345678abcdef01";
    render(<BoardActionsList {...baseProps} actions={[action({ actionId })]} />);
    expect(screen.getByLabelText(`Action ${actionId}`)).toHaveTextContent(actionId);
  });
});

describe("BoardActionsList staff hand-off", () => {
  it("hides the control when staff is off", () => {
    render(<BoardActionsList {...baseProps} actions={[action()]} seats={[prospector]} isStaffEnabled={false} onAssignToStaff={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Hand to staff", hidden: true })).toBeNull();
  });

  it("pre-fills the brief from the action and sends actionId", () => {
    const onAssignToStaff = vi.fn();
    render(
      <BoardActionsList {...baseProps} actions={[action()]} seats={[prospector]} isStaffEnabled onAssignToStaff={onAssignToStaff} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "More actions" }));
    fireEvent.click(screen.getByRole("button", { name: "Hand to staff", hidden: true }));
    const brief = screen.getByLabelText("Brief") as HTMLTextAreaElement;
    expect(brief.value).toContain("Call 10 activity providers");
    expect(brief.value).toContain("Done looks like: Book calls with providers in Sha Tin.");
    expect(brief.value).toContain("Success metric: 10 calls booked");
    expect((screen.getByLabelText("Assignee") as HTMLSelectElement).value).toBe("prospector");
    fireEvent.click(screen.getByRole("button", { name: "Assign task" }));
    expect(onAssignToStaff).toHaveBeenCalledWith({
      assignee: "prospector",
      brief: brief.value,
      deliverableType: "markdown",
      slaHours: 24,
      actionId: "a1",
    });
  });

  it("shows who is working the action and hides the control once a task exists", () => {
    const onOpenStaffTask = vi.fn();
    render(
      <BoardActionsList
        {...baseProps}
        actions={[action({ assignee: "prospector", staffTaskId: "t9" })]}
        seats={[prospector]}
        isStaffEnabled
        onAssignToStaff={vi.fn()}
        onOpenStaffTask={onOpenStaffTask}
      />,
    );
    expect(screen.getByText(/staff: Priya/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Hand to staff", hidden: true })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "open task" }));
    expect(onOpenStaffTask).toHaveBeenCalledWith("t9");
  });
});
