import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  AdminRowActions,
} from "../ui";
import { BoardTaskId } from "./BoardTaskId";
import {
  canRetryBoardTask,
  formatUsageCost,
  taskSlaLabel,
  taskSlaState,
  taskStatusLabel,
  taskStatusTone,
  type BoardTask,
} from "../../lib/boardModel";

const COLUMNS = [
  { key: "task", header: "Task" },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "assignee", header: "Assignee", priority: "secondary" as const },
  { key: "sla", header: "SLA", priority: "tertiary" as const },
  { key: "steps", header: "Steps", priority: "tertiary" as const },
  { key: "cost", header: "Cost", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span> },
] as const;

export function BoardTasksTable({
  tasks,
  query,
  onQueryChange,
  actorLabel,
  nowMs,
  retryingId,
  cancellingId,
  onOpen,
  onRetry,
  onCancel,
}: {
  readonly tasks: readonly BoardTask[];
  readonly query: string;
  readonly onQueryChange: (value: string) => void;
  readonly actorLabel: (id: string) => string;
  readonly nowMs: number;
  readonly retryingId: string | null;
  readonly cancellingId: string | null;
  readonly onOpen: (taskId: string) => void;
  readonly onRetry: (taskId: string) => void;
  readonly onCancel: (taskId: string) => void;
}) {
  return (
    <AdminDataTable
      columns={COLUMNS}
      filterValue={query}
      onFilterChange={onQueryChange}
      filterPlaceholder="Search brief, assignee, or task id…"
    >
      {tasks.length === 0 ? (
        <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No tasks match this view." />
      ) : (
        tasks.map((task) => {
          const sla = taskSlaState(task.slaAt, nowMs, task.status);
          const busy = retryingId === task.taskId || cancellingId === task.taskId;
          return (
            <tr key={task.taskId}>
              <AdminCell column="task">
                <div className="d-flex flex-wrap align-items-center gap-2">
                  <BoardTaskId taskId={task.taskId} compact />
                  <button type="button" className="btn btn-link btn-sm p-0 text-start" onClick={() => onOpen(task.taskId)}>
                    <span className="board-clamp-1">{task.brief}</span>
                  </button>
                </div>
                <AdminDataTableCellMeta>
                  <span className={`badge text-bg-${taskStatusTone(task.status)} me-1`}>{taskStatusLabel(task.status)}</span>
                  {actorLabel(task.assignee)}
                </AdminDataTableCellMeta>
              </AdminCell>
              <AdminCell column="status">
                <span className={`badge text-bg-${taskStatusTone(task.status)}`}>{taskStatusLabel(task.status)}</span>
              </AdminCell>
              <AdminCell column="assignee">{actorLabel(task.assignee)}</AdminCell>
              <AdminCell column="sla">
                <span className={sla === "overdue" ? "text-danger" : sla === "soon" ? "text-warning" : undefined}>
                  {taskSlaLabel(task.slaAt, nowMs, task.status)}
                </span>
              </AdminCell>
              <AdminCell column="steps">{task.stepsUsed}</AdminCell>
              <AdminCell column="cost">{formatUsageCost(task.usage.cost)}</AdminCell>
              <AdminCell column="ops" className="text-nowrap">
                <AdminRowActions
                  actions={[
                    {
                      id: "open",
                      label: `Open task ${task.taskId}`,
                      iconClassName: "bi bi-box-arrow-up-right",
                      onClick: () => onOpen(task.taskId),
                    },
                    {
                      id: "retry",
                      label: `Retry task ${task.taskId}`,
                      iconClassName: "bi bi-arrow-repeat",
                      hidden: !canRetryBoardTask(task.status),
                      disabled: busy,
                      onClick: () => onRetry(task.taskId),
                    },
                    {
                      id: "dismiss",
                      label: `Dismiss task ${task.taskId}`,
                      iconClassName: "bi bi-x-lg",
                      danger: true,
                      hidden: task.status !== "failed",
                      disabled: busy,
                      onClick: () => onCancel(task.taskId),
                    },
                  ]}
                />
              </AdminCell>
            </tr>
          );
        })
      )}
    </AdminDataTable>
  );
}
