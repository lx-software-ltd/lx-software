import { useMemo, useState } from "react";
import { AdminEditorSection } from "../ui";
import { BoardTaskDrawer } from "./BoardTaskDrawer";
import { BoardNewTaskForm } from "./BoardNewTaskForm";
import { formatUsageCost, type BoardSeat, type BoardTask } from "../../lib/boardModel";
import { BOARD_PERSONA_DEFAULTS, BOARD_STAFF_MODEL_TIERS } from "../../lib/contracts/generated";
import { staffTickErrorMessage, useBoardStaff } from "../../hooks/useBoardStaff";
import { useBoardTask, useBoardTasks } from "../../hooks/useBoardTasks";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";

const COLUMNS: readonly {
  readonly id: "queued" | "running" | "review" | "needs_owner" | "delivered" | "failed";
  readonly label: string;
}[] = [
  { id: "queued", label: "Queued" },
  { id: "running", label: "Running" },
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

export function BoardStaffSection({ focusTaskId = null }: { readonly focusTaskId?: string | null }) {
  const staff = useBoardStaff();
  const tasks = useBoardTasks();
  // The section unmounts when the owner leaves it, so the initial focus is enough.
  const [selectedId, setSelectedId] = useState<string | null>(focusTaskId);
  const detail = useBoardTask(selectedId);
  const byManager = useMemo(() => {
    const groups = new Map<string, BoardSeat[]>();
    for (const seat of staff.seats) {
      const list = groups.get(seat.reportsTo) ?? [];
      list.push(seat);
      groups.set(seat.reportsTo, list);
    }
    return groups;
  }, [staff.seats]);

  return (
    <div>
      <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary"
          disabled={!staff.enabled || staff.tick.isPending}
          onClick={() => staff.tick.mutate()}
        >
          {staff.tick.isPending ? "Queuing tick…" : "Run staff tick now"}
        </button>
        <span className="small text-muted">
          Same work as the 5-minute schedule: due duties, due holds, then drain the queue. Runs in the background.
        </span>
      </div>
      {staff.tick.isSuccess ? (
        <p className="small text-muted">
          {staff.tick.data?.droppedByBrowser
            ? "The browser dropped the response. If nothing moves into Running within five minutes, the scheduled tick will still run."
            : "Tick queued. Queued work should move into Running within a few seconds if a seat is free; this list refreshes on its own."}
        </p>
      ) : null}
      {staffTickErrorMessage(staff.tick.error) ? (
        <div className="alert alert-danger py-2 small">{staffTickErrorMessage(staff.tick.error)}</div>
      ) : null}
      {!staff.enabled ? (
        <p className="small text-muted">
          Staff tasks are off. Turn on <code>settings.staff.enabled</code> after <code>SiutindeiBoardStaffEnabled</code> is true
          on the stack.
        </p>
      ) : null}
      <div className="row g-3 mb-4">
        {[...byManager.entries()].map(([managerId, seats]) => {
          const manager = BOARD_PERSONA_DEFAULTS.find((p) => p.id === managerId);
          return (
            <div className="col-12" key={managerId}>
              <h3 className="h6 text-uppercase text-muted mb-2">{manager?.title ?? managerId}</h3>
              <div className="row g-3">
                {seats.map((seat) => (
                  <div className="col-12 col-lg-6" key={seat.id}>
                    <SeatCard
                      seat={seat}
                      isSaving={staff.override.isPending || staff.reset.isPending}
                      onSave={(override) => staff.override.mutate({ seatId: seat.id, override })}
                      onReset={() => staff.reset.mutate(seat.id)}
                    />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <BoardNewTaskForm
        seats={staff.seats}
        disabled={!staff.enabled || tasks.create.isPending}
        errorMessage={errorText(tasks.create.error)}
        onCreate={(body) => tasks.create.mutate(body)}
      />

      {errorText(tasks.error) ? <div className="alert alert-danger py-2 small">{errorText(tasks.error)}</div> : null}
      {errorText(tasks.retry.error) ? <div className="alert alert-danger py-2 small">{errorText(tasks.retry.error)}</div> : null}
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
                  onOpen={() => setSelectedId(task.taskId)}
                  onRetry={task.status === "failed" ? () => tasks.retry.mutate(task.taskId) : undefined}
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
          onCancel={(id) => tasks.cancel.mutate(id)}
          onReview={(id, verdict, notes) => tasks.review.mutate({ taskId: id, verdict, notes })}
          onRetry={(id) => tasks.retry.mutate(id)}
        />
      ) : null}
    </div>
  );
}

function SeatCard({
  seat,
  isSaving,
  onSave,
  onReset,
}: {
  readonly seat: BoardSeat;
  readonly isSaving: boolean;
  readonly onSave: (override: { displayName?: string; brief?: string; isActive?: boolean; modelTier?: "desk" | "senior" }) => void;
  readonly onReset: () => void;
}) {
  const [brief, setBrief] = useState(seat.isOverridden.brief ? seat.brief : "");
  const [name, setName] = useState(seat.isOverridden.displayName ? seat.displayName : "");
  return (
    <AdminEditorSection
      title={seat.displayName}
      description={`${seat.title} · reports to ${seat.reportsTo}`}
      footer={
        <>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={isSaving}
            onClick={() =>
              onSave({
                displayName: name.trim() || undefined,
                brief: brief.trim() || undefined,
                isActive: seat.isActive,
                modelTier: seat.modelTier,
              })
            }
          >
            Save brief
          </button>
          <button type="button" className="btn btn-outline-secondary btn-sm" disabled={isSaving} onClick={onReset}>
            Use default
          </button>
        </>
      }
    >
      <div className="form-check form-switch mb-2">
        <input
          className="form-check-input"
          type="checkbox"
          id={`seat-active-${seat.id}`}
          checked={seat.isActive}
          onChange={(ev) => onSave({ isActive: ev.target.checked })}
        />
        <label className="form-check-label" htmlFor={`seat-active-${seat.id}`}>
          Active
        </label>
      </div>
      <label className="form-label small">
        Model tier
        <select
          className="form-select form-select-sm"
          value={seat.modelTier}
          onChange={(ev) => onSave({ modelTier: ev.target.value as "desk" | "senior" })}
        >
          {BOARD_STAFF_MODEL_TIERS.map((tier) => (
            <option key={tier} value={tier}>
              {tier}
            </option>
          ))}
        </select>
      </label>
      <label className="form-label small">
        Display name
        <input className="form-control form-control-sm" value={name} onChange={(ev) => setName(ev.target.value)} placeholder={seat.defaults.displayName} />
      </label>
      <label className="form-label small mb-0">
        Brief
        <textarea className="form-control form-control-sm" rows={4} value={brief} onChange={(ev) => setBrief(ev.target.value)} placeholder={seat.defaults.brief} />
      </label>
    </AdminEditorSection>
  );
}

function TaskCard({
  task,
  isRetrying,
  onOpen,
  onRetry,
}: {
  readonly task: BoardTask;
  readonly isRetrying: boolean;
  readonly onOpen: () => void;
  readonly onRetry?: () => void;
}) {
  return (
    <div className={`card shadow-sm mb-2 text-start w-100 ${task.status === "failed" ? "border-danger-subtle" : "border"}`}>
      <button type="button" className="card-body py-2 px-3 btn text-start border-0" onClick={onOpen}>
        <div className="small fw-semibold">{task.brief.slice(0, 90)}</div>
        <div className="small text-muted">
          {eventSourceLabel(task)}
          {task.assignee} · {formatUsageCost(task.usage.cost)}
        </div>
        {task.status === "failed" && task.failureReason ? (
          <div className="small text-danger mt-1">{task.failureReason}</div>
        ) : null}
      </button>
      {onRetry ? (
        <div className="card-footer py-1 px-2 bg-transparent border-0">
          <button type="button" className="btn btn-sm btn-outline-primary" disabled={isRetrying} onClick={onRetry}>
            {isRetrying ? "Retrying…" : "Retry"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
