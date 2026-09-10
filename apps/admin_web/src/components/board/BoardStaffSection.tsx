import { useMemo, useState } from "react";
import { AdminEditorSection } from "../ui";
import { BoardTaskDrawer } from "./BoardTaskDrawer";
import { formatUsageCost, type BoardSeat, type BoardTask, type BoardTaskCreate } from "../../lib/boardModel";
import { BOARD_PERSONA_DEFAULTS, BOARD_STAFF_DELIVERABLE_TYPES, BOARD_STAFF_MODEL_TIERS } from "../../lib/contracts/generated";
import { useBoardStaff } from "../../hooks/useBoardStaff";
import { useBoardTask, useBoardTasks } from "../../hooks/useBoardTasks";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";

const COLUMNS: readonly { readonly id: "queued" | "running" | "review" | "needs_owner" | "delivered"; readonly label: string }[] = [
  { id: "queued", label: "Queued" },
  { id: "running", label: "Running" },
  { id: "review", label: "Review" },
  { id: "needs_owner", label: "Needs owner" },
  { id: "delivered", label: "Delivered" },
];

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

export function BoardStaffSection() {
  const staff = useBoardStaff();
  const tasks = useBoardTasks();
  const [selectedId, setSelectedId] = useState<string | null>(null);
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
      {!staff.enabled ? (
        <p className="small text-muted">
          Staff tasks are off. Turn on <code>settings.staff.enabled</code> after <code>BoardStaffEnabled</code> is true
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

      <NewTaskForm
        seats={staff.seats}
        disabled={!staff.enabled || tasks.create.isPending}
        errorMessage={errorText(tasks.create.error)}
        onCreate={(body) => tasks.create.mutate(body)}
      />

      {errorText(tasks.error) ? <div className="alert alert-danger py-2 small">{errorText(tasks.error)}</div> : null}
      <div className="row g-3">
        {COLUMNS.map((col) => {
          const items = tasks.tasks.filter((t) => t.status === col.id);
          return (
            <div className="col-12 col-xl" key={col.id}>
              <div className="small text-uppercase text-muted mb-2">
                {col.label} ({items.length})
              </div>
              {items.map((task) => (
                <TaskCard key={task.taskId} task={task} onOpen={() => setSelectedId(task.taskId)} />
              ))}
            </div>
          );
        })}
      </div>

      {selectedId ? (
        <BoardTaskDrawer
          detail={detail.data}
          isLoading={detail.isLoading}
          isMutating={tasks.cancel.isPending || tasks.review.isPending}
          errorMessage={errorText(detail.error) ?? errorText(tasks.cancel.error) ?? errorText(tasks.review.error)}
          onClose={() => setSelectedId(null)}
          onCancel={(id) => tasks.cancel.mutate(id)}
          onReview={(id, verdict, notes) => tasks.review.mutate({ taskId: id, verdict, notes })}
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

function TaskCard({ task, onOpen }: { readonly task: BoardTask; readonly onOpen: () => void }) {
  return (
    <button type="button" className="card shadow-sm mb-2 text-start w-100 border" onClick={onOpen}>
      <div className="card-body py-2 px-3">
        <div className="small fw-semibold">{task.brief.slice(0, 90)}</div>
        <div className="small text-muted">
          {task.assignee} · {formatUsageCost(task.usage.cost)}
        </div>
      </div>
    </button>
  );
}

function NewTaskForm({
  seats,
  disabled,
  errorMessage,
  onCreate,
}: {
  readonly seats: readonly BoardSeat[];
  readonly disabled: boolean;
  readonly errorMessage?: string | null;
  readonly onCreate: (body: BoardTaskCreate) => void;
}) {
  const [assignee, setAssignee] = useState("cfo");
  const [brief, setBrief] = useState("");
  const [deliverableType, setDeliverableType] = useState<(typeof BOARD_STAFF_DELIVERABLE_TYPES)[number]>("markdown");
  const personas = BOARD_PERSONA_DEFAULTS.map((p) => ({ id: p.id, label: `${p.shortName} (${p.title})` }));
  const activeSeats = seats.filter((s) => s.isActive).map((s) => ({ id: s.id, label: `${s.displayName} · seat` }));
  return (
    <AdminEditorSection title="New task" description="Assign work to an executive or an active seat.">
      <div className="row g-3">
        <div className="col-md-4">
          <label className="form-label small">
            Assignee
            <select className="form-select form-select-sm" value={assignee} onChange={(ev) => setAssignee(ev.target.value)}>
              <optgroup label="Board">
                {personas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </optgroup>
              {activeSeats.length ? (
                <optgroup label="Staff">
                  {activeSeats.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label}
                    </option>
                  ))}
                </optgroup>
              ) : null}
            </select>
          </label>
        </div>
        <div className="col-md-3">
          <label className="form-label small">
            Deliverable
            <select
              className="form-select form-select-sm"
              value={deliverableType}
              onChange={(ev) => setDeliverableType(ev.target.value as (typeof BOARD_STAFF_DELIVERABLE_TYPES)[number])}
            >
              {BOARD_STAFF_DELIVERABLE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="col-12">
          <label className="form-label small">
            Brief
            <textarea className="form-control form-control-sm" rows={2} value={brief} onChange={(ev) => setBrief(ev.target.value)} />
          </label>
        </div>
        <div className="col-12">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={disabled || !brief.trim()}
            onClick={() => onCreate({ assignee, brief: brief.trim(), deliverableType, slaHours: 24 })}
          >
            Create task
          </button>
          {errorMessage ? <span className="small text-danger ms-2">{errorMessage}</span> : null}
        </div>
      </div>
    </AdminEditorSection>
  );
}
