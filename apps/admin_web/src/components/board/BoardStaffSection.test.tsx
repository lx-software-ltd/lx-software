import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BoardStaffSection } from "./BoardStaffSection";

vi.mock("../../hooks/useBoardStaff", () => ({
  useBoardStaff: () => ({
    enabled: true,
    envEnabled: true,
    seats: [
      {
        id: "support",
        title: "Parent Support",
        displayName: "Sam",
        reportsTo: "coo",
        brief: "Help parents.",
        defaults: { displayName: "Sam", brief: "Help parents." },
        isOverridden: { displayName: false, brief: false },
        isActive: true,
        modelTier: "desk",
      },
    ],
    counts: { needs_owner: 1 },
    isLoading: false,
    isError: false,
    error: null,
    override: { isPending: false, mutate: vi.fn() },
    reset: { isPending: false, mutate: vi.fn() },
    tick: { isPending: false, isSuccess: false, error: null, data: null, mutate: vi.fn() },
  }),
  staffTickErrorMessage: () => null,
}));

describe("BoardStaffSection", () => {
  it("shows the roster and tick, not the task board", () => {
    render(<BoardStaffSection maxRunningTasks={8} />);
    expect(screen.getByRole("button", { name: "Run staff tick now" })).toBeInTheDocument();
    expect(screen.getByText(/Parent Support/)).toBeInTheDocument();
    expect(screen.getByText(/Up to 8 tasks can run at once/)).toBeInTheDocument();
    expect(screen.getByText(/Open work and new assignments live on the Tasks tab/)).toBeInTheDocument();
    expect(screen.queryByText("New task")).not.toBeInTheDocument();
    expect(screen.queryByText(/Failed \(/)).not.toBeInTheDocument();
  });

  it("links to Settings for the concurrent-task cap", () => {
    const onOpenSettings = vi.fn();
    render(<BoardStaffSection maxRunningTasks={3} onOpenSettings={onOpenSettings} />);
    screen.getByRole("button", { name: "Open Settings" }).click();
    expect(onOpenSettings).toHaveBeenCalledTimes(1);
  });
});
