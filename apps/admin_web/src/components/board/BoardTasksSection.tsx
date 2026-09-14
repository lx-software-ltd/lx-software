import { useState } from "react";
import { BoardTaskDrawer } from "./BoardTaskDrawer";
import { BoardNewTaskForm } from "./BoardNewTaskForm";
import { canRetryBoardTask, formatUsageCost, type BoardTask } from "../../lib/boardModel";
import { useBoardStaff } from "../../hooks/useBoardStaff";
import { useBoardTask, useBoardTasks } from "../../hooks/useBoardTasks";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";

const COLUMNS: readonly {
  readonly id: "queued" | "running" | "waiting_approval" | "waiting_subtask" | "review" | "needs_owner" | "delivered" | "failed";
  readonly label: string;
}[] = [
  { id: "queued", label: "Queued" },
  { id: "running", label: "Running" },
  { id: "waiting_approval", label: "Waiting approval" },
  { id: "waiting_subtask", label: "Waiting help" },
  { id: "review", label: "Review" },
  { id: "needs_owner", label: "Needs owner" },
  { id: "delivered", label: "Delivered" },
  { id: "failed", label: "Failed" },
];

function eventSourceLabel(task: BoardTask): string {
  const ref = task.eventRef;
  if (!ref) return "";
  if (ref.kind === "mail") return "✉ mail · ";
  if (ref.kind === "review") return `★ ${ref.stars ?? ""} review · `;
  if (ref.kind === "meta") return `${ref.channel || "meta"} · `;
  return `${ref.kind} · `;
}

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

export function BoardTasksSection({ focusTaskId = null }: { readonly focusTaskId?: string | null }) {
  const staff = useBoardStaff();
  const tasks = useBoardTasks();
  // The section unmounts when the owner leaves it, so the initial focus is enough.
  const [selectedId, setSelectedId] = useState<string | null>(focusTaskId);
  const detail = useBoardTask(selectedId);

  return (
    <div>
      {!staff.enabled ? (
        <p className="small text-muted">
          Staff tasks are off. Turn on <code>settings.staff.enabled</code> after <code>SiutindeiBoardStaffEnabled</code> is true
          on the stack. Seats are managed on the Staff tab.
        </p>
      ) : null}

      <BoardNewTaskForm
        seats={staff.seats}
        disabled={!staff.enabled || tasks.create.isPending}
        errorMessage={errorText(tasks.create.error)}
        onCreate={(body) => tasks.create.mutate(body)}
      />

      {errorText(tasks.error) ? <div className="alert alert-danger py-2 small">{errorText(tasks.error)}</div> : null}
      {errorText(tasks.retry.error) ? <div className="alert alert-danger py-2 small">{errorText(tasks.retry.error)}</div> : null}
      {errorText(tasks.cancel.error) ? <div className="alert alert-danger py-2 small">{errorText(tasks.cancel.error)}</div> : null}
      <div className="row g-3">
        {COLUMNS.map((col) => {
          const items = tasks.tasks.filter((t) => t.status === col.id);
          return (
            <div className="col-12 col-xl" key={col.id}>
              <div className="small text-uppercase text-muted mb-2">
                {col.label} ({items.length})
              </div>
              {items.map((task) => (
                <TaskCard
                  key={task.taskId}
                  task={task}
                  isRetrying={tasks.retry.isPending}
                  isCancelling={tasks.cancel.isPending}
                  onOpen={() => setSelectedId(task.taskId)}
                  onRetry={canRetryBoardTask(task.status) ? () => tasks.retry.mutate(task.taskId) : undefined}
                  onCancel={task.status === "failed" ? () => tasks.cancel.mutate(task.taskId) : undefined}
                />
              ))}
            </div>
          );
        })}
      </div>

      {selectedId ? (
        <BoardTaskDrawer
          detail={detail.data}
          isLoading={detail.isLoading}
          isMutating={tasks.cancel.isPending || tasks.review.isPending || tasks.retry.isPending}
          errorMessage={
            errorText(detail.error) ??
            errorText(tasks.cancel.error) ??
            errorText(tasks.review.error) ??
            errorText(tasks.retry.error)
          }
          onClose={() => setSelectedId(null)}
          onCancel={(id) => tasks.cancel.mutate(id, { onSuccess: () => setSelectedId(null) })}
          onReview={(id, verdict, notes) => tasks.review.mutate({ taskId: id, verdict, notes })}
          onRetry={(id) => tasks.retry.mutate(id)}
        />
      ) : null}
    </div>
  );
}

function TaskCard({
  task,
  isRetrying,
  isCancelling,
  onOpen,
  onRetry,
  onCancel,
}: {
  readonly task: BoardTask;
  readonly isRetrying: boolean;
  readonly isCancelling: boolean;
  readonly onOpen: () => void;
  readonly onRetry?: () => void;
  readonly onCancel?: () => void;
}) {
  const busy = isRetrying || isCancelling;
  return (
    <div className={`card shadow-sm mb-2 text-start w-100 ${task.status === "failed" ? "border-danger-subtle" : "border"}`}>
      <button type="button" className="card-body py-2 px-3 btn text-start border-0" onClick={onOpen}>
        <div className="small fw-semibold">{task.brief.slice(0, 90)}</div>
        <div className="small text-muted">
          {eventSourceLabel(task)}
          {task.parentTaskId ? "help · " : ""}
          {task.helpTaskIds?.length ? "asked help · " : ""}
          {task.assignee} · {formatUsageCost(task.usage.cost)}
        </div>
        {task.status === "failed" && task.failureReason ? (
          <div className="small text-danger mt-1">{task.failureReason}</div>
        ) : null}
      </button>
      {onRetry || onCancel ? (
        <div className="card-footer py-1 px-2 bg-transparent border-0 d-flex gap-2">
          {onRetry ? (
            <button type="button" className="btn btn-sm btn-outline-primary" disabled={busy} onClick={onRetry}>
              {isRetrying ? "Retrying…" : "Retry"}
            </button>
          ) : null}
          {onCancel ? (
            <button type="button" className="btn btn-sm btn-outline-danger" disabled={busy} onClick={onCancel}>
              {isCancelling ? "Dismissing…" : "Dismiss"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
