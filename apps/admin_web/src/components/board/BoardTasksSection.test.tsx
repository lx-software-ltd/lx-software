import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardTask } from "../../lib/boardModel";
import { BoardTasksSection } from "./BoardTasksSection";

const retryMutate = vi.fn();
const cancelMutate = vi.fn();
const cancelState = { isPending: false, error: null as unknown, mutate: cancelMutate };

const failedTask: BoardTask = {
  taskId: "task-failed",
  status: "failed",
  assignee: "engineer-1",
  assigneeKind: "seat",
  managerId: "cto",
  origin: "owner",
  brief: "Complete backend integration and performance tuning.",
  deliverableType: "markdown",
  budgetUsd: 1,
  slaAt: "2026-09-14T00:00:00Z",
  step: 12,
  stepsUsed: 12,
  revisions: 0,
  usage: { promptTokens: 100, completionTokens: 20, cost: 0.03, calls: 4 },
  summary: "",
  evidence: [],
  openQuestions: [],
  confidence: "",
  reviews: 0,
  lastReview: null,
  createdAt: "2026-09-13T11:45:52Z",
  updatedAt: "2026-09-13T11:49:21Z",
  failureReason: "step limit",
};

const ownerTask: BoardTask = {
  ...failedTask,
  taskId: "task-owner",
  status: "needs_owner",
  assignee: "community-manager",
  managerId: "cmo",
  brief: "Verify GA4 visitor sources.",
  step: 3,
  stepsUsed: 3,
  revisions: 2,
  failureReason: "",
  lastReview: { verdict: "return", notes: "Need evidence.", at: "2026-09-14T00:00:00Z" },
};

vi.mock("../../hooks/useBoardStaff", () => ({
  useBoardStaff: () => ({
    enabled: true,
    envEnabled: true,
    seats: [],
    counts: { failed: 1 },
    isLoading: false,
    isError: false,
    error: null,
    override: { isPending: false, mutate: vi.fn() },
    reset: { isPending: false, mutate: vi.fn() },
    tick: { isPending: false, isSuccess: false, error: null, data: null, mutate: vi.fn() },
  }),
  staffTickErrorMessage: () => null,
}));

vi.mock("../../hooks/useBoardTasks", () => ({
  useBoardTasks: () => ({
    tasks: [failedTask, ownerTask],
    counts: { failed: 1, needs_owner: 1 },
    isLoading: false,
    isError: false,
    error: null,
    create: { isPending: false, error: null, mutate: vi.fn() },
    cancel: cancelState,
    review: { isPending: false, error: null, mutate: vi.fn() },
    retry: { isPending: false, error: null, mutate: retryMutate },
  }),
  useBoardTask: () => ({ data: undefined, isLoading: false, error: null }),
}));

describe("BoardTasksSection", () => {
  it("shows failed tasks and can retry or dismiss them", () => {
    render(<BoardTasksSection />);
    expect(screen.getByText("New task")).toBeInTheDocument();
    expect(screen.getByText(/Failed \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Needs owner \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Waiting approval \(0\)/)).toBeInTheDocument();
    expect(screen.getByText("step limit")).toBeInTheDocument();
    const retries = screen.getAllByRole("button", { name: "Retry" });
    expect(retries).toHaveLength(2);
    fireEvent.click(retries[0]);
    expect(retryMutate).toHaveBeenCalledWith("task-owner");
    fireEvent.click(retries[1]);
    expect(retryMutate).toHaveBeenCalledWith("task-failed");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(cancelMutate).toHaveBeenCalledWith("task-failed");
  });

  it("surfaces a dismiss error above the board when the drawer is closed", () => {
    cancelState.error = new Error("Delivered tasks cannot be cancelled");
    render(<BoardTasksSection />);
    expect(screen.getByText("Delivered tasks cannot be cancelled")).toBeInTheDocument();
    cancelState.error = null;
  });
});
