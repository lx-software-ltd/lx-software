import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardTask, BoardTaskDetailPayload } from "../../lib/boardModel";
import { BoardTaskDrawer } from "./BoardTaskDrawer";

const catalogTask: BoardTask = {
  taskId: "task-catalog",
  status: "delivered",
  assignee: "content-marketer",
  assigneeKind: "seat",
  managerId: "cmo",
  origin: "duty",
  brief: "Founder directive — CATALOG MICRO-BATCH Eastern.",
  deliverableType: "json",
  budgetUsd: 3,
  slaAt: "2026-09-16T00:00:00Z",
  step: 4,
  stepsUsed: 4,
  revisions: 0,
  usage: { promptTokens: 10, completionTokens: 4, cost: 0.01, calls: 2 },
  summary: "Three organisations.",
  evidence: [],
  openQuestions: [],
  confidence: "high",
  reviews: 1,
  lastReview: { verdict: "accept", notes: "", at: "2026-09-16T00:00:00Z" },
  createdAt: "2026-09-15T00:00:00Z",
  updatedAt: "2026-09-16T00:00:00Z",
  eventRef: { kind: "catalog-micro-batch", id: "catalog:eastern", district: "Eastern" },
  importPreview: {
    ok: true,
    district: "Eastern",
    importEnabled: false,
    dryRun: { ok: true, accepted: 1, skipped: 0 },
    payload: { organizations: [{ name: "Quarry Bay Park Playground", category_name: "Playground", area_name: "Eastern" }] },
  },
};

const detail: BoardTaskDetailPayload = {
  task: catalogTask,
  steps: [],
  reviews: [],
  deliverable: '{"district":"Eastern"}',
  deliverableUrl: "",
};

describe("BoardTaskDrawer catalog import", () => {
  it("shows preview and import on a delivered catalog sheet", () => {
    const onPreview = vi.fn();
    const onImport = vi.fn();
    render(
      <BoardTaskDrawer
        detail={detail}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
        onPreviewImport={onPreview}
        onImport={onImport}
      />,
    );
    expect(screen.getByText("Quarry Bay Park Playground — Playground / Eastern")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(onPreview).toHaveBeenCalledWith("task-catalog");
    expect(onImport).toHaveBeenCalledWith("task-catalog");
  });
});
