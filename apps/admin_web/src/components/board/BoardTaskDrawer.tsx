import { useMemo, useState } from "react";
import { BoardMarkdown } from "./BoardMarkdown";
import { BoardOffcanvas } from "./BoardOffcanvas";
import { BoardToolCallList } from "./BoardToolCallList";
import { DateTimeDisplay } from "../ui";
import { formatUsageCost, type BoardTask, type BoardTaskDetailPayload, type BoardToolCallLogEntry } from "../../lib/boardModel";

export type BoardTaskDrawerProps = {
  readonly detail: BoardTaskDetailPayload | undefined;
  readonly isLoading: boolean;
  readonly isMutating: boolean;
  readonly errorMessage?: string | null;
  readonly onClose: () => void;
  readonly onCancel: (taskId: string) => void;
  readonly onReview: (taskId: string, verdict: "accept" | "return", notes: string) => void;
};

const OPEN_STATUSES = new Set(["queued", "running", "review", "returned", "needs_owner"]);

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
}: BoardTaskDrawerProps) {
  const [notes, setNotes] = useState("");
  const task = detail?.task;
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
      subtitle={task ? `${task.assignee} · ${task.status} · ${formatUsageCost(task.usage.cost)}` : undefined}
      onClose={onClose}
      footer={
        task && OPEN_STATUSES.has(task.status) ? (
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
            <button
              type="button"
              className="btn btn-outline-danger btn-sm"
              disabled={isMutating}
              onClick={() => onCancel(task.taskId)}
            >
              Cancel
            </button>
          </>
        ) : null
      }
    >
      {isLoading && !task ? <p className="text-muted small">Loading task…</p> : null}
      {errorMessage ? <div className="alert alert-danger py-2 small">{errorMessage}</div> : null}
      {task ? <TaskBody task={task} detail={detail} calls={calls} notes={notes} onNotes={setNotes} /> : null}
    </BoardOffcanvas>
  );
}

function TaskBody({
  task,
  detail,
  calls,
  notes,
  onNotes,
}: {
  readonly task: BoardTask;
  readonly detail: BoardTaskDetailPayload | undefined;
  readonly calls: readonly BoardToolCallLogEntry[];
  readonly notes: string;
  readonly onNotes: (value: string) => void;
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
        {deliverable ? (
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
      {task.status === "review" || task.status === "needs_owner" ? (
        <label className="form-label small mb-0">
          Review notes
          <textarea className="form-control form-control-sm mt-1" rows={3} value={notes} onChange={(ev) => onNotes(ev.target.value)} />
        </label>
      ) : null}
    </div>
  );
}
