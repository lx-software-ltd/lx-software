import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BoardTask, BoardTaskDetailPayload, BoardToolCallLogEntry } from "../../lib/boardModel";
import { BoardTaskDrawer } from "./BoardTaskDrawer";

const loggedCalls = vi.hoisted(() => ({ current: [] as BoardToolCallLogEntry[] }));

vi.mock("../../hooks/useBoardTools", () => ({
  useBoardToolCalls: () => ({ data: loggedCalls.current }),
}));

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
    dryRun: { ok: true, mode: "local", accepted: 1, skipped: 0 },
    payload: { organizations: [{ name: "Quarry Bay Park Playground", category_name: "Outdoor activity", area_name: "Eastern" }] },
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
  beforeEach(() => {
    loggedCalls.current = [];
  });

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
    expect(screen.getByText("Quarry Bay Park Playground — Outdoor activity / Eastern")).toBeInTheDocument();
    expect(document.querySelector(".board-json-preview")).toHaveTextContent('"district": "Eastern"');
    expect(screen.getByText(/local dry-run/)).toBeInTheDocument();
    expect(screen.getByText(/import kill switch off/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    expect(onPreview).toHaveBeenCalledWith("task-catalog");
    expect(screen.getByRole("button", { name: "Import now" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Import now" }));
    expect(onImport).not.toHaveBeenCalled();
  });

  it("labels Preview import as Previewing while the remote dry-run is in flight", () => {
    render(
      <BoardTaskDrawer
        detail={detail}
        isLoading={false}
        isMutating
        isPreviewing
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
        onPreviewImport={() => undefined}
      />,
    );
    expect(screen.getByRole("button", { name: "Previewing…" })).toBeDisabled();
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

  it("shows automatic re-validation progress on a parked sheet", () => {
    render(
      <BoardTaskDrawer
        detail={{
          ...detail,
          task: {
            ...catalogTask,
            status: "needs_owner",
            importPhase: "invalid",
            revalidateAttempts: 2,
          },
        }}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
      />,
    );
    expect(screen.getByText("Automatic re-validation: 2/3")).toBeInTheDocument();
  });

  it("says automatic re-validation stopped after three attempts", () => {
    render(
      <BoardTaskDrawer
        detail={{
          ...detail,
          task: {
            ...catalogTask,
            status: "needs_owner",
            importPhase: "rejected",
            revalidateAttempts: 3,
          },
        }}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
      />,
    );
    expect(screen.getByText(/Automatic re-validation: 3\/3/)).toBeInTheDocument();
    expect(screen.getByText(/stopped; Preview or Requeue to try again/)).toBeInTheDocument();
  });

  it("hides Accept on an import collision", () => {
    render(
      <BoardTaskDrawer
        detail={{
          ...detail,
          task: {
            ...catalogTask,
            status: "needs_owner",
            importPhase: "collision",
            importPreview: {
              ...catalogTask.importPreview!,
              dryRun: { ok: true, mode: "remote", accepted: 1, skipped: 0, wouldUpdate: ["Kidz Club"] },
            },
          },
        }}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
        onImport={() => undefined}
        onSkipImport={() => undefined}
        onRequeueImport={() => undefined}
      />,
    );
    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import anyway" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Queue again" })).toBeInTheDocument();
    expect(screen.getByText(/remote dry-run/)).toBeInTheDocument();
  });

  it("surfaces skip and requeue errors in the catalog panel", () => {
    render(
      <BoardTaskDrawer
        detail={detail}
        isLoading={false}
        isMutating={false}
        importMessage="Could not skip this sheet"
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
        onSkipImport={() => undefined}
      />,
    );
    expect(screen.getByText("Could not skip this sheet")).toBeInTheDocument();
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

  it("offers re-import on an already-imported sheet", () => {
    const onReimport = vi.fn();
    render(
      <BoardTaskDrawer
        detail={{
          ...detail,
          task: { ...catalogTask, status: "delivered", importedAt: "2026-09-16T00:00:00Z", importPhase: "imported" },
        }}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
        onReimport={onReimport}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Re-import failed rows" }));
    expect(onReimport).toHaveBeenCalledWith("task-catalog");
  });

  it("shows the finished JSON under the step title", () => {
    loggedCalls.current = [
      {
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
      },
    ];
    render(
      <BoardTaskDrawer
        detail={{
          ...detail,
          steps: [{ seq: 1, plan: "Write the sheet.", callIds: ["call-finish"], at: "2026-11-08T01:30:00Z" }],
        }}
        isLoading={false}
        isMutating={false}
        onClose={() => undefined}
        onCancel={() => undefined}
        onReview={() => undefined}
      />,
    );
    const step = screen.getByText("Finished the task").closest("li");
    expect(step?.querySelector(".board-finish-preview")).toHaveTextContent("Quarry Bay Park");
  });
});
