import { BoardTaskId } from "./BoardTaskId";
import {
  formatRelativeTime,
  formatUsageCost,
  shortTaskId,
  taskSlaLabel,
  taskSlaState,
  taskStatusLabel,
  taskStatusTone,
  taskStepsLimit,
  type BoardTask,
} from "../../lib/boardModel";

export function BoardTaskCard({
  task,
  assigneeLabel,
  managerLabel,
  isRetrying,
  isCancelling,
  errorMessage,
  onOpen,
  onOpenTask,
  onRetry,
  onCancel,
}: {
  readonly task: BoardTask;
  readonly assigneeLabel: string;
  readonly managerLabel: string;
  readonly isRetrying: boolean;
  readonly isCancelling: boolean;
  readonly errorMessage?: string | null;
  readonly onOpen: () => void;
  readonly onOpenTask: (taskId: string) => void;
  readonly onRetry?: () => void;
  readonly onCancel?: () => void;
}) {
  const busy = isRetrying || isCancelling;
  const tone = taskStatusTone(task.status);
  const sla = taskSlaState(task.slaAt, Date.now(), task.status);
  const stepsMax = taskStepsLimit();
  const stepPct = Math.min(100, Math.round((task.stepsUsed / Math.max(stepsMax, 1)) * 100));
  const budgetPct = task.budgetUsd > 0 ? Math.min(100, Math.round((task.usage.cost / task.budgetUsd) * 100)) : 0;
  const origin = originChip(task);
  const context = contextLine(task);
  return (
    <div
      className={`card shadow-sm mb-0 text-start w-100 board-task-card ${
        task.status === "failed" ? "border-danger-subtle" : "border"
      }`}
    >
      <div className="card-body py-2 px-3">
        <div className="d-flex justify-content-between align-items-start gap-2 mb-1">
          <span className={`badge text-bg-${tone}`}>{taskStatusLabel(task.status)}</span>
          <BoardTaskId taskId={task.taskId} compact />
        </div>
        <button type="button" className="btn text-start border-0 p-0 w-100" onClick={onOpen}>
          <span className="d-block small fw-semibold board-clamp-2" title={task.brief}>
            {task.brief}
          </span>
          <span className="d-block small text-muted mt-1">
            {assigneeLabel}
            {managerLabel && managerLabel !== assigneeLabel ? ` → ${managerLabel}` : ""}
            {origin ? <span className="badge text-bg-light border ms-1">{origin}</span> : null}
          </span>
          <span className="d-block mt-2">
            <span
              className="board-task-meter"
              role="meter"
              aria-label={`Steps ${task.stepsUsed} of ${stepsMax}`}
              aria-valuemin={0}
              aria-valuemax={stepsMax}
              aria-valuenow={task.stepsUsed}
            >
              <span className="board-task-meter-fill" style={{ width: `${stepPct}%` }} />
            </span>
            <span
              className="board-task-meter board-task-meter-budget mt-1"
              role="meter"
              aria-label={`Spend ${formatUsageCost(task.usage.cost)} of ${formatUsageCost(task.budgetUsd)}`}
              aria-valuemin={0}
              aria-valuemax={task.budgetUsd || 0}
              aria-valuenow={task.usage.cost}
            >
              <span className="board-task-meter-fill" style={{ width: `${budgetPct}%` }} />
            </span>
          </span>
          <span className="d-block small text-muted mt-1">
            {task.stepsUsed} / {stepsMax} steps · {formatUsageCost(task.usage.cost)}
            {task.budgetUsd ? ` / ${formatUsageCost(task.budgetUsd)}` : ""}
          </span>
          <span className={`d-block small mt-1 ${sla === "overdue" ? "text-danger" : sla === "soon" ? "text-warning" : "text-muted"}`}>
            {taskSlaLabel(task.slaAt, Date.now(), task.status)} · updated {formatRelativeTime(task.updatedAt)}
          </span>
        </button>
        {task.parentTaskId ? (
          <div className="small mt-1">
            ↳ help for <TaskIdLink taskId={task.parentTaskId} onOpenTask={onOpenTask} />
          </div>
        ) : null}
        {task.helpTaskIds?.length ? (
          <div className="small mt-1">
            asked help ({task.helpTaskIds.length}){" "}
            {task.helpTaskIds.map((id) => (
              <TaskIdLink key={id} taskId={id} onOpenTask={onOpenTask} />
            ))}
          </div>
        ) : null}
        {context ? <div className={`small mt-1 ${task.status === "failed" ? "text-danger" : "text-muted"}`}>{context}</div> : null}
      </div>
      {onRetry || onCancel ? (
        <div className="card-footer py-1 px-2 bg-transparent border-0 d-flex flex-wrap gap-2">
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
      {errorMessage ? <div className="px-3 pb-2 small text-danger">{errorMessage}</div> : null}
    </div>
  );
}

function TaskIdLink({
  taskId,
  onOpenTask,
}: {
  readonly taskId: string;
  readonly onOpenTask: (taskId: string) => void;
}) {
  return (
    <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => onOpenTask(taskId)}>
      #{shortTaskId(taskId)}
    </button>
  );
}

function originChip(task: BoardTask): string {
  const ref = task.eventRef;
  if (ref) {
    if (ref.kind === "mail") return "mail";
    if (ref.kind === "review") return `${ref.stars ?? ""}★ review`.trim();
    if (ref.kind === "meta") return ref.channel || "meta";
    return ref.kind || "";
  }
  if (task.origin === "duty") return "duty";
  if (task.origin === "minutes") return "minutes";
  if (task.origin === "task") return "help";
  return "";
}

function contextLine(task: BoardTask): string {
  if (task.status === "failed" && task.failureReason) return task.failureReason;
  if (task.parkedReason) return task.parkedReason;
  if (task.lastReview?.notes) return `${task.lastReview.verdict}: ${task.lastReview.notes}`;
  return "";
}
