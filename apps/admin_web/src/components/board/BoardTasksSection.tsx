import { useCallback, useEffect, useMemo, useState } from "react";
import { BoardNewTaskForm } from "./BoardNewTaskForm";
import { BoardOffcanvas } from "./BoardOffcanvas";
import { BoardTaskCard } from "./BoardTaskCard";
import { BoardTaskDrawer } from "./BoardTaskDrawer";
import { BoardTasksTable } from "./BoardTasksTable";
import {
  BOARD_PERSONA_DEFAULTS,
  BOARD_STAFF_SEAT_DEFAULTS,
} from "../../lib/contracts/generated";
import {
  BOARD_TASK_LANES,
  BOARD_TASK_STATUS_META,
  TASK_DONE_LANE_PREVIEW,
  canRetryBoardTask,
  filterBoardTasks,
  formatRelativeTime,
  formatUsageCost,
  groupTasksByLane,
  isFinishedBoardTaskStatus,
  sumTaskUsageCost,
  syncBoardTaskSearchParams,
  taskActorLabel,
  type BoardTaskLaneId,
  type BoardTaskStatus,
} from "../../lib/boardModel";
import { useBoardStaff } from "../../hooks/useBoardStaff";
import { useBoardTask, useBoardTasks } from "../../hooks/useBoardTasks";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

function defaultView(): "board" | "list" {
  if (typeof window === "undefined") return "board";
  const narrow =
    window.innerWidth < 768 ||
    (typeof window.matchMedia === "function" && !window.matchMedia("(min-width: 768px)").matches);
  return narrow ? "list" : "board";
}

export function BoardTasksSection({
  focusTaskId = null,
  onFocusConsumed,
}: {
  readonly focusTaskId?: string | null;
  readonly onFocusConsumed?: () => void;
}) {
  const staff = useBoardStaff();
  const [includeFinished, setIncludeFinished] = useState(false);
  const [query, setQuery] = useState("");
  const [assignee, setAssignee] = useState("");
  const [statusFilter, setStatusFilter] = useState<BoardTaskStatus | "">("");
  const [view, setView] = useState<"board" | "list">(defaultView);
  const [phoneLane, setPhoneLane] = useState<BoardTaskLaneId>("attention");
  const [doneExpanded, setDoneExpanded] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [pickedId, setPickedId] = useState<string | null>(focusTaskId);
  const [appliedFocus, setAppliedFocus] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  if (focusTaskId && focusTaskId !== appliedFocus) {
    setAppliedFocus(focusTaskId);
    if (pickedId !== focusTaskId) setPickedId(focusTaskId);
  } else if (!focusTaskId && appliedFocus) {
    setAppliedFocus(null);
  }
  const selectedId = pickedId;
  const tasks = useBoardTasks();
  const detail = useBoardTask(selectedId);

  useEffect(() => {
    if (focusTaskId) onFocusConsumed?.();
  }, [focusTaskId, onFocusConsumed]);

  useEffect(() => {
    syncBoardTaskSearchParams(selectedId);
  }, [selectedId]);

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const actorLabel = useCallback((id: string) => taskActorLabel(id, staff.seats), [staff.seats]);
  const visible = useMemo(
    () =>
      filterBoardTasks(tasks.tasks, {
        query,
        assignee,
        status: statusFilter,
        includeFinished: includeFinished || statusFilter === "delivered" || statusFilter === "cancelled",
        actorLabel,
      }),
    [tasks.tasks, query, assignee, statusFilter, includeFinished, actorLabel],
  );
  const lanes = useMemo(() => groupTasksByLane(visible), [visible]);
  const spend = sumTaskUsageCost(tasks.tasks.filter((task) => !isFinishedBoardTaskStatus(task.status)));
  const retryingId = tasks.retry.isPending ? String(tasks.retry.variables ?? "") : null;
  const cancellingId = tasks.cancel.isPending ? String(tasks.cancel.variables ?? "") : null;
  const updatedLabel = tasks.dataUpdatedAt
    ? formatRelativeTime(new Date(tasks.dataUpdatedAt).toISOString(), nowMs)
    : "just now";

  const openTask = (taskId: string) => {
    setPickedId(taskId);
    onFocusConsumed?.();
  };
  const closeTask = () => {
    setPickedId(null);
    onFocusConsumed?.();
  };
  const assignees = useMemo(() => {
    const seen = new Set<string>();
    const rows: { id: string; label: string }[] = [];
    for (const seat of staff.seats) {
      if (seen.has(seat.id)) continue;
      seen.add(seat.id);
      rows.push({ id: seat.id, label: seat.displayName || seat.title });
    }
    for (const seat of BOARD_STAFF_SEAT_DEFAULTS) {
      if (seen.has(seat.id)) continue;
      seen.add(seat.id);
      rows.push({ id: seat.id, label: seat.title });
    }
    for (const persona of BOARD_PERSONA_DEFAULTS) {
      if (seen.has(persona.id)) continue;
      seen.add(persona.id);
      rows.push({ id: persona.id, label: persona.shortName });
    }
    return rows;
  }, [staff.seats]);

  const selectStatus = (status: BoardTaskStatus) => {
    const next = statusFilter === status ? "" : status;
    setStatusFilter(next);
    if (isFinishedBoardTaskStatus(status)) setIncludeFinished(true);
    const lane = BOARD_TASK_LANES.find((row) => row.statuses.includes(status));
    if (lane) setPhoneLane(lane.id);
  };

  return (
    <div>
      {!staff.enabled ? (
        <p className="small text-muted">
          Staff tasks are off. Turn them on under Settings → Staff and daily review after the stack kill switch is on.
          Seats are managed on the Staff tab.
        </p>
      ) : null}

      <SummaryStrip
        counts={tasks.counts}
        fallbackTasks={tasks.tasks}
        active={statusFilter}
        spend={spend}
        isFetching={tasks.isFetching}
        updatedLabel={updatedLabel}
        onSelect={selectStatus}
      />

      <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={!staff.enabled}
          onClick={() => setShowNew(true)}
        >
          New task
        </button>
        {view === "board" ? (
          <input
            type="search"
            className="form-control form-control-sm board-task-search"
            placeholder="Search brief, assignee, or task id…"
            value={query}
            onChange={(ev) => setQuery(ev.target.value)}
            aria-label="Search tasks"
          />
        ) : null}
        <select
          className="form-select form-select-sm board-task-assignee"
          value={assignee}
          onChange={(ev) => setAssignee(ev.target.value)}
          aria-label="Filter by assignee"
        >
          <option value="">All assignees</option>
          {assignees.map((row) => (
            <option key={row.id} value={row.id}>
              {row.label}
            </option>
          ))}
        </select>
        <div className="btn-group" role="group" aria-label="Task view">
          <button type="button" className={`btn btn-sm btn-outline-secondary ${view === "board" ? "active" : ""}`} onClick={() => setView("board")}>
            Board
          </button>
          <button type="button" className={`btn btn-sm btn-outline-secondary ${view === "list" ? "active" : ""}`} onClick={() => setView("list")}>
            List
          </button>
        </div>
        <div className="form-check mb-0">
          <input
            id="board-tasks-show-finished"
            className="form-check-input"
            type="checkbox"
            checked={includeFinished}
            onChange={(ev) => setIncludeFinished(ev.target.checked)}
          />
          <label className="form-check-label small" htmlFor="board-tasks-show-finished">
            Show finished
          </label>
        </div>
      </div>

      {errorText(tasks.error) ? <div className="alert alert-danger py-2 small">{errorText(tasks.error)}</div> : null}
      {errorText(tasks.retry.error) && !visible.some((task) => task.taskId === String(tasks.retry.variables ?? "")) ? (
        <div className="alert alert-danger py-2 small">{errorText(tasks.retry.error)}</div>
      ) : null}
      {errorText(tasks.cancel.error) && !visible.some((task) => task.taskId === String(tasks.cancel.variables ?? "")) ? (
        <div className="alert alert-danger py-2 small">{errorText(tasks.cancel.error)}</div>
      ) : null}

      {tasks.isLoading && visible.length === 0 ? <p className="small text-muted">Loading tasks…</p> : null}

      {view === "list" ? (
        <BoardTasksTable
          tasks={visible}
          query={query}
          onQueryChange={setQuery}
          actorLabel={actorLabel}
          retryingId={retryingId}
          cancellingId={cancellingId}
          onOpen={openTask}
          onRetry={(id) => tasks.retry.mutate(id)}
          onCancel={(id) => tasks.cancel.mutate(id)}
        />
      ) : (
        <>
          <div className="d-md-none mb-3">
            <label className="visually-hidden" htmlFor="board-task-lane-select">
              Task lane
            </label>
            <select
              id="board-task-lane-select"
              className="form-select form-select-sm"
              value={phoneLane}
              onChange={(ev) => setPhoneLane(ev.target.value as BoardTaskLaneId)}
            >
              {BOARD_TASK_LANES.map((lane) => (
                <option key={lane.id} value={lane.id}>
                  {lane.label} ({lanes[lane.id].length})
                </option>
              ))}
            </select>
          </div>
          <div className="board-task-lanes">
            {BOARD_TASK_LANES.map((lane) => {
              const items = lanes[lane.id];
              const preview = lane.id === "done" && !doneExpanded && items.length > TASK_DONE_LANE_PREVIEW;
              const shown = preview ? items.slice(0, TASK_DONE_LANE_PREVIEW) : items;
              return (
                <section
                  key={lane.id}
                  className={`board-task-lane ${phoneLane === lane.id ? "" : "d-none d-md-flex"}`}
                  aria-label={lane.label}
                >
                  <div className="board-task-lane-head small text-uppercase text-muted">
                    {lane.label} ({items.length})
                  </div>
                  {shown.length === 0 ? <p className="small text-muted mb-0">{lane.empty}</p> : null}
                  {shown.map((task) => (
                    <BoardTaskCard
                      key={task.taskId}
                      task={task}
                      assigneeLabel={actorLabel(task.assignee)}
                      managerLabel={actorLabel(task.managerId)}
                      isRetrying={retryingId === task.taskId}
                      isCancelling={cancellingId === task.taskId}
                      errorMessage={
                        selectedId === task.taskId
                          ? null
                          : ((retryingId === task.taskId || String(tasks.retry.variables ?? "") === task.taskId
                              ? errorText(tasks.retry.error)
                              : null) ??
                            (cancellingId === task.taskId || String(tasks.cancel.variables ?? "") === task.taskId
                              ? errorText(tasks.cancel.error)
                              : null))
                      }
                      onOpen={() => openTask(task.taskId)}
                      onOpenTask={openTask}
                      onRetry={canRetryBoardTask(task.status) ? () => tasks.retry.mutate(task.taskId) : undefined}
                      onCancel={task.status === "failed" ? () => tasks.cancel.mutate(task.taskId) : undefined}
                    />
                  ))}
                  {preview ? (
                    <button type="button" className="btn btn-link btn-sm px-0" onClick={() => setDoneExpanded(true)}>
                      Show all {items.length}
                    </button>
                  ) : null}
                </section>
              );
            })}
          </div>
        </>
      )}

      {showNew ? (
        <BoardOffcanvas isOpen title="New task" onClose={() => setShowNew(false)}>
          <BoardNewTaskForm
            seats={staff.seats}
            disabled={!staff.enabled || tasks.create.isPending}
            errorMessage={errorText(tasks.create.error)}
            title=""
            embedded
            onCreate={(body) =>
              tasks.create.mutate(body, {
                onSuccess: (created) => {
                  setShowNew(false);
                  if (created?.taskId) openTask(created.taskId);
                },
              })
            }
          />
        </BoardOffcanvas>
      ) : null}

      {selectedId ? (
        <BoardTaskDrawer
          detail={detail.data}
          isLoading={detail.isLoading}
          isMutating={
            tasks.cancel.isPending ||
            tasks.review.isPending ||
            tasks.retry.isPending ||
            tasks.catalogPreview.isPending ||
            tasks.catalogImport.isPending
          }
          errorMessage={
            errorText(detail.error) ??
            errorText(tasks.cancel.error) ??
            errorText(tasks.review.error) ??
            errorText(tasks.retry.error)
          }
          importPreview={tasks.catalogPreview.data ?? detail.data?.task.importPreview}
          importMessage={errorText(tasks.catalogImport.error) ?? errorText(tasks.catalogPreview.error)}
          onClose={closeTask}
          onOpenTask={openTask}
          onCancel={(id) => tasks.cancel.mutate(id, { onSuccess: () => closeTask() })}
          onReview={(id, verdict, notes) => tasks.review.mutate({ taskId: id, verdict, notes })}
          onRetry={(id) => tasks.retry.mutate(id)}
          onPreviewImport={(id) => tasks.catalogPreview.mutate(id)}
          onImport={(id) => tasks.catalogImport.mutate(id)}
        />
      ) : null}
    </div>
  );
}

function SummaryStrip({
  counts,
  fallbackTasks,
  active,
  spend,
  isFetching,
  updatedLabel,
  onSelect,
}: {
  readonly counts: Readonly<Record<string, number>>;
  readonly fallbackTasks: readonly { readonly status: string }[];
  readonly active: BoardTaskStatus | "";
  readonly spend: number;
  readonly isFetching: boolean;
  readonly updatedLabel: string;
  readonly onSelect: (status: BoardTaskStatus) => void;
}) {
  return (
    <div className="d-flex flex-wrap justify-content-between align-items-start gap-2 mb-3">
      <div className="d-flex flex-wrap gap-2" role="toolbar" aria-label="Task status filters">
        {BOARD_TASK_STATUS_META.filter((row) => row.id !== "cancelled" || countFor(row.id, counts, fallbackTasks) > 0).map(
          (row) => {
            const count = countFor(row.id, counts, fallbackTasks);
            const isActive = active === row.id;
            return (
              <button
                key={row.id}
                type="button"
                className={`btn btn-sm btn-outline-${row.tone} ${isActive ? "active" : ""}`}
                onClick={() => onSelect(row.id)}
              >
                {row.label} ({count})
              </button>
            );
          },
        )}
      </div>
      <div className="small text-muted text-md-end" aria-live="polite">
        <div>Open task spend {formatUsageCost(spend)}</div>
        <div>{isFetching ? "Refreshing…" : `Updated ${updatedLabel}`}</div>
      </div>
    </div>
  );
}

function countFor(
  status: string,
  counts: Readonly<Record<string, number>>,
  tasks: readonly { readonly status: string }[],
): number {
  if (typeof counts[status] === "number") return counts[status];
  return tasks.filter((task) => task.status === status).length;
}
