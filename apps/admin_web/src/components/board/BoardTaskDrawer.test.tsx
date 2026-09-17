import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardTask, BoardTaskDetailPayload } from "../../lib/boardModel";
import { BoardTaskDrawer } from "./BoardTaskDrawer";

const catalogTask: BoardTask = {
  taskId: "task-catalog",
  status: "awaiting_import",
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
    taskId: "task-catalog",
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
  it("shows preview and disables Import while the kill switch is off", () => {
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
    expect(screen.getByText(/import kill switch off/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    expect(onPreview).toHaveBeenCalledWith("task-catalog");
    expect(screen.getByRole("button", { name: "Import now" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Import now" }));
    expect(onImport).not.toHaveBeenCalled();
  });

  it("imports a waiting sheet when the kill switch is on", () => {
    const onImport = vi.fn();
    render(
      <BoardTaskDrawer
        detail={{
          ...detail,
          task: {
            ...catalogTask,
            importPreview: { ...catalogTask.importPreview!, importEnabled: true },
          },
        }}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
        onImport={onImport}
        importPreview={{ ...catalogTask.importPreview!, importEnabled: true }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Import now" }));
    expect(onImport).toHaveBeenCalledWith("task-catalog");
  });

  it("offers skip on a waiting sheet", () => {
    const onSkip = vi.fn();
    render(
      <BoardTaskDrawer
        detail={detail}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
        onSkipImport={onSkip}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Skip import" }));
    expect(onSkip).toHaveBeenCalledWith("task-catalog");
  });

  it("formats importedAt with DateTimeDisplay", () => {
    render(
      <BoardTaskDrawer
        detail={{
          ...detail,
          task: { ...catalogTask, importedAt: "2026-09-16T00:00:00Z" },
        }}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
      />,
    );
    expect(screen.getByText(/Imported/)).toBeInTheDocument();
    expect(screen.getAllByText("September 16, 2026 at 8:00am HKT").length).toBeGreaterThan(0);
    expect(screen.queryByText("2026-09-16T00:00:00Z")).not.toBeInTheDocument();
  });
});
