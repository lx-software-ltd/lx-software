import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardTask } from "../../lib/boardModel";
import { BoardTasksSection } from "./BoardTasksSection";

const retryMutate = vi.fn();
const cancelMutate = vi.fn();

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
    tasks: [failedTask],
    counts: { failed: 1 },
    isLoading: false,
    isError: false,
    error: null,
    create: { isPending: false, error: null, mutate: vi.fn() },
    cancel: { isPending: false, error: null, mutate: cancelMutate },
    review: { isPending: false, error: null, mutate: vi.fn() },
    retry: { isPending: false, error: null, mutate: retryMutate },
  }),
  useBoardTask: () => ({ data: undefined, isLoading: false, error: null }),
}));

describe("BoardTasksSection", () => {
  it("shows failed tasks and can retry or cancel them", () => {
    render(<BoardTasksSection />);
    expect(screen.getByText("New task")).toBeInTheDocument();
    expect(screen.getByText(/Failed \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Waiting approval \(0\)/)).toBeInTheDocument();
    expect(screen.getByText("step limit")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retryMutate).toHaveBeenCalledWith("task-failed");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(cancelMutate).toHaveBeenCalledWith("task-failed");
  });
});
