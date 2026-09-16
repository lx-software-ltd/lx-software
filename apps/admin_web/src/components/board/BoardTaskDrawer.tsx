import { useMemo, useState } from "react";
import { BoardMarkdown } from "./BoardMarkdown";
import { BoardOffcanvas } from "./BoardOffcanvas";
import { BoardTaskId } from "./BoardTaskId";
import { BoardToolCallList } from "./BoardToolCallList";
import { DateTimeDisplay } from "../ui";
import {
  canRetryBoardTask,
  formatUsageCost,
  isCatalogSheetTask,
  shortTaskId,
  type BoardCatalogImportPreview,
  type BoardTask,
  type BoardTaskDetailPayload,
  type BoardToolCallLogEntry,
} from "../../lib/boardModel";

export type BoardTaskDrawerProps = {
  readonly detail: BoardTaskDetailPayload | undefined;
  readonly isLoading: boolean;
  readonly isMutating: boolean;
  readonly errorMessage?: string | null;
  readonly onClose: () => void;
  readonly onCancel: (taskId: string) => void;
  readonly onReview: (taskId: string, verdict: "accept" | "return", notes: string) => void;
  readonly onRetry?: (taskId: string) => void;
  readonly onOpenTask?: (taskId: string) => void;
  readonly onPreviewImport?: (taskId: string) => void;
  readonly onImport?: (taskId: string) => void;
  readonly importPreview?: BoardCatalogImportPreview | null;
  readonly importMessage?: string | null;
};

const OPEN_STATUSES = new Set([
  "queued",
  "running",
  "waiting_approval",
  "waiting_subtask",
  "review",
  "returned",
  "needs_owner",
]);

function csvRows(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .filter((line) => line.trim())
    .map((line) => line.split(",").map((cell) => cell.trim()));
}

export function BoardTaskDrawer({
  detail,
  isLoading,
  isMutating,
  errorMessage,
  onClose,
  onCancel,
  onReview,
  onRetry,
  onOpenTask,
  onPreviewImport,
  onImport,
  importPreview,
  importMessage,
}: BoardTaskDrawerProps) {
  const [notes, setNotes] = useState("");
  const task = detail?.task;
  const preview = importPreview ?? task?.importPreview;
  const calls = useMemo<BoardToolCallLogEntry[]>(() => {
    const ids = new Set(detail?.steps.flatMap((s) => s.callIds) ?? []);
    return (detail?.steps ?? []).flatMap((step) =>
      step.callIds
        .filter((id) => ids.has(id))
        .map((callId) => ({
          callId,
          op: callId,
          toolId: "task",
          toolLabel: "Tool",
          kind: "read" as const,
          status: "ok" as const,
          summary: step.plan.slice(0, 80) || callId,
          durationMs: 0,
          personaId: task?.assignee ?? "",
          displayName: task?.assignee ?? "",
          actor: "persona" as const,
          level: "act" as const,
          arguments: {},
          resultPreview: "",
          context: { kind: "task" },
          createdAt: step.at,
        })),
    );
  }, [detail, task?.assignee]);

  return (
    <BoardOffcanvas
      isOpen
      wide
      title={task ? task.brief.slice(0, 80) || task.taskId : "Task"}
      subtitle={
        task ? (
          <span className="d-flex flex-wrap align-items-center gap-2">
            <BoardTaskId taskId={task.taskId} full />
            <span>
              {task.assignee} · {task.status} · {formatUsageCost(task.usage.cost)}
            </span>
          </span>
        ) : undefined
      }
      onClose={onClose}
      footer={
        task && (OPEN_STATUSES.has(task.status) || task.status === "failed" || (task.status === "delivered" && isCatalogSheetTask(task))) ? (
          <>
            {task.status === "review" || task.status === "needs_owner" ? (
              <>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={isMutating}
                  onClick={() => onReview(task.taskId, "accept", notes)}
                >
                  Accept
                </button>
                <button
                  type="button"
                  className="btn btn-outline-primary btn-sm"
                  disabled={isMutating}
                  onClick={() => onReview(task.taskId, "return", notes)}
                >
                  Return
                </button>
              </>
            ) : null}
            {isCatalogSheetTask(task) && onPreviewImport ? (
              <button
                type="button"
                className="btn btn-outline-primary btn-sm"
                disabled={isMutating}
                onClick={() => onPreviewImport(task.taskId)}
              >
                Preview import
              </button>
            ) : null}
            {isCatalogSheetTask(task) && onImport && task.status === "delivered" ? (
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                disabled={
                  isMutating ||
                  Boolean(task.importedAt) ||
                  preview?.importEnabled === false
                }
                onClick={() => onImport(task.taskId)}
              >
                {task.importedAt ? "Imported" : "Import"}
              </button>
            ) : null}
            {canRetryBoardTask(task.status) && onRetry ? (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={isMutating}
                onClick={() => onRetry(task.taskId)}
              >
                Retry
              </button>
            ) : null}
            {OPEN_STATUSES.has(task.status) || task.status === "failed" ? (
              <button
                type="button"
                className="btn btn-outline-danger btn-sm"
                disabled={isMutating}
                onClick={() => onCancel(task.taskId)}
              >
                {task.status === "failed" ? "Dismiss" : "Cancel"}
              </button>
            ) : null}
          </>
        ) : null
      }
    >
      {isLoading && !task ? <p className="text-muted small">Loading task…</p> : null}
      {errorMessage ? <div className="alert alert-danger py-2 small">{errorMessage}</div> : null}
      {task ? (
        <TaskBody
          task={task}
          detail={detail}
          calls={calls}
          notes={notes}
          onNotes={setNotes}
          onOpenTask={onOpenTask}
          importPreview={preview}
          importMessage={importMessage}
        />
      ) : null}
    </BoardOffcanvas>
  );
}

function TaskBody({
  task,
  detail,
  calls,
  notes,
  onNotes,
  onOpenTask,
  importPreview,
  importMessage,
}: {
  readonly task: BoardTask;
  readonly detail: BoardTaskDetailPayload | undefined;
  readonly calls: readonly BoardToolCallLogEntry[];
  readonly notes: string;
  readonly onNotes: (value: string) => void;
  readonly onOpenTask?: (taskId: string) => void;
  readonly importPreview?: BoardCatalogImportPreview | null;
  readonly importMessage?: string | null;
}) {
  const deliverable = detail?.deliverable ?? "";
  const isCsv = task.deliverableType === "csv";
  const rows = isCsv ? csvRows(deliverable) : [];
  return (
    <div className="d-flex flex-column gap-3">
      <div>
        <div className="small text-muted text-uppercase">Brief</div>
        <p className="mb-0">{task.brief}</p>
      </div>
      {task.status === "failed" && task.failureReason ? (
        <div>
          <div className="small text-muted text-uppercase">Failure</div>
          <p className="mb-0 text-danger">{task.failureReason}</p>
        </div>
      ) : null}
      {task.parentTaskId ? (
        <div>
          <div className="small text-muted text-uppercase">Help for</div>
          <p className="mb-0">
            Parent task{" "}
            <RelatedTaskId taskId={task.parentTaskId} onOpenTask={onOpenTask} />
          </p>
        </div>
      ) : null}
      {task.helpTaskIds && task.helpTaskIds.length > 0 ? (
        <div>
          <div className="small text-muted text-uppercase">Help tasks</div>
          <p className="mb-0">
            {task.helpTaskIds.map((id) => (
              <RelatedTaskId key={id} taskId={id} onOpenTask={onOpenTask} />
            ))}
          </p>
        </div>
      ) : null}
      {task.lastReview ? (
        <div>
          <div className="small text-muted text-uppercase">Last review</div>
          <p className="mb-0">
            <strong>{task.lastReview.verdict}</strong> — {task.lastReview.notes || "No notes."}{" "}
            <span className="text-muted">
              (<DateTimeDisplay iso={task.lastReview.at} />)
            </span>
          </p>
        </div>
      ) : null}
      <div>
        <div className="small text-muted text-uppercase mb-1">Steps</div>
        {(detail?.steps ?? []).length === 0 ? <p className="small text-muted mb-0">No steps yet.</p> : null}
        {(detail?.steps ?? []).map((step) => (
          <details key={step.seq} className="mb-2">
            <summary className="small">
              Step {step.seq}: {step.plan.slice(0, 80) || "no note"}
            </summary>
            <p className="small mb-1 mt-2">{step.plan}</p>
            {step.callIds.length ? (
              <BoardToolCallList calls={calls.filter((c) => step.callIds.includes(c.callId))} className="small" />
            ) : null}
          </details>
        ))}
      </div>
      <div>
        <div className="small text-muted text-uppercase mb-1">Deliverable</div>
        {task.deliverableType === "messages" && deliverable ? (
          <MessagesDeliverable text={deliverable} />
        ) : deliverable ? (
          isCsv && rows.length ? (
            <div className="table-responsive">
              <table className="table table-sm">
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <BoardMarkdown text={deliverable} className="small" />
          )
        ) : (
          <p className="small text-muted mb-0">No deliverable yet.</p>
        )}
      </div>
      {isCatalogSheetTask(task) ? (
        <CatalogImportPanel preview={importPreview} importedAt={task.importedAt} message={importMessage} />
      ) : null}
      {task.status === "review" || task.status === "needs_owner" ? (
        <label className="form-label small mb-0">
          Review notes
          <textarea className="form-control form-control-sm mt-1" rows={3} value={notes} onChange={(ev) => onNotes(ev.target.value)} />
        </label>
      ) : null}
    </div>
  );
}

function RelatedTaskId({
  taskId,
  onOpenTask,
}: {
  readonly taskId: string;
  readonly onOpenTask?: (taskId: string) => void;
}) {
  if (!onOpenTask) {
    return (
      <code className="me-2" title={taskId}>
        #{shortTaskId(taskId)}
      </code>
    );
  }
  return (
    <button type="button" className="btn btn-link btn-sm p-0 me-2 align-baseline" onClick={() => onOpenTask(taskId)}>
      #{shortTaskId(taskId)}
    </button>
  );
}

function CatalogImportPanel({
  preview,
  importedAt,
  message,
}: {
  readonly preview?: BoardCatalogImportPreview | null;
  readonly importedAt?: string;
  readonly message?: string | null;
}) {
  const orgs = preview?.payload?.organizations ?? [];
  return (
    <div>
      <div className="small text-muted text-uppercase mb-1">Catalog import</div>
      {importedAt ? (
        <p className="small mb-1">
          Imported <DateTimeDisplay iso={importedAt} />
        </p>
      ) : null}
      {message ? <div className="alert alert-warning py-2 small mb-2">{message}</div> : null}
      {preview?.error ? <div className="alert alert-danger py-2 small mb-2">{preview.error}</div> : null}
      {preview ? (
        <p className="small mb-1">
          {preview.district || "Unknown district"} · {preview.dryRun?.accepted ?? 0} ready, {preview.dryRun?.skipped ?? 0}{" "}
          skipped
          {preview.importEnabled ? "" : " · import kill switch off"}
        </p>
      ) : (
        <p className="small text-muted mb-1">Accept the sheet or click Preview import to map verified fields.</p>
      )}
      {orgs.length > 0 ? (
        <ul className="small mb-0">
          {orgs.map((org, i) => (
            <li key={i}>
              {String(org.name || "Organisation")} — {String(org.category_name || "")} / {String(org.area_name || "")}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function MessagesDeliverable({ text }: { readonly text: string }) {
  let rows: Array<{ status?: string; summary?: string; threadId?: string; op?: string }> = [];
  try {
    const parsed = JSON.parse(text) as unknown;
    rows = Array.isArray(parsed) ? parsed : [];
  } catch {
    return <BoardMarkdown text={text} className="small" />;
  }
  if (rows.length === 0) return <p className="small text-muted mb-0">No messages recorded.</p>;
  return (
    <ul className="list-unstyled mb-0">
      {rows.map((row, i) => (
        <li key={i} className="small mb-2">
          <span className="badge text-bg-light border me-1">{row.status || row.op || "message"}</span>
          {row.summary || ""}
          {row.threadId ? (
            <a className="ms-2" href={`#mail-${row.threadId}`}>
              open thread
            </a>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
