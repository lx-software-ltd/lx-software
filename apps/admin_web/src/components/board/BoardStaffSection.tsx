import { useMemo, useState } from "react";
import { AdminEditorSection } from "../ui";
import type { BoardSeat } from "../../lib/boardModel";
import {
  BOARD_PERSONA_DEFAULTS,
  BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT,
  BOARD_STAFF_MODEL_TIERS,
  BOARD_STAFF_STEP_MODELS,
} from "../../lib/contracts/generated";
import { staffTickErrorMessage, useBoardStaff } from "../../hooks/useBoardStaff";

const SEAT_MODEL_LABELS: Record<string, string> = {
  "qwen/qwen-2.5-72b-instruct": "Qwen 2.5 72B (tool-heavy)",
  "deepseek/deepseek-chat": "DeepSeek Chat",
};

const SEAT_MODEL_CHOICES = [
  { value: "", label: "Tier default" },
  ...BOARD_STAFF_STEP_MODELS.map((id) => ({ value: id, label: SEAT_MODEL_LABELS[id] ?? id })),
] as const;

export type BoardStaffSectionProps = {
  readonly maxRunningTasks?: number;
  readonly onOpenSettings?: () => void;
  readonly modelBySeat?: Readonly<Record<string, string>>;
  readonly onSaveModel?: (seatId: string, model: string) => void;
};

export function BoardStaffSection({ maxRunningTasks, onOpenSettings, modelBySeat, onSaveModel }: BoardStaffSectionProps) {
  const staff = useBoardStaff();
  const runningCap = maxRunningTasks ?? BOARD_STAFF_MAX_RUNNING_TASKS_DEFAULT;
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
          Staff tasks are off. Turn them on under Settings → Staff and daily review after the stack kill switch is on.
          Open work lives on the Tasks tab.
        </p>
      ) : (
        <p className="small text-muted">
          Up to {runningCap} tasks can run at once. Extra work stays queued. Change the cap under Settings → Staff and
          daily review. Open work and new assignments live on the Tasks tab.
        </p>
      )}
      {onOpenSettings ? (
        <p className="mb-3">
          <button type="button" className="btn btn-link btn-sm p-0" onClick={onOpenSettings}>
            Open Settings
          </button>
        </p>
      ) : null}
      <div className="row g-3 mb-4">
        {[...byManager.entries()].map(([managerId, seats]) => {
          const manager = BOARD_PERSONA_DEFAULTS.find((p) => p.id === managerId);
          return (
            <div className="col-12" key={managerId}>
              <h3 className="admin-card-title">{manager?.title ?? managerId}</h3>
              <div className="row g-3">
                {seats.map((seat) => (
                  <div className="col-12 col-lg-6" key={seat.id}>
                    <SeatCard
                      seat={seat}
                      isSaving={staff.override.isPending || staff.reset.isPending}
                      onSave={(override) => staff.override.mutate({ seatId: seat.id, override })}
                      onReset={() => staff.reset.mutate(seat.id)}
                      model={modelBySeat?.[seat.id] ?? ""}
                      onSaveModel={onSaveModel ? (model) => onSaveModel(seat.id, model) : undefined}
                    />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SeatCard({
  seat,
  isSaving,
  onSave,
  onReset,
  model,
  onSaveModel,
}: {
  readonly seat: BoardSeat;
  readonly isSaving: boolean;
  readonly onSave: (override: { displayName?: string; brief?: string; isActive?: boolean; modelTier?: "desk" | "senior" }) => void;
  readonly onReset: () => void;
  readonly model?: string;
  readonly onSaveModel?: (model: string) => void;
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
      {onSaveModel ? (
        <label className="form-label small">
          Step model
          <select
            className="form-select form-select-sm"
            value={model ?? ""}
            onChange={(ev) => onSaveModel(ev.target.value)}
          >
            {SEAT_MODEL_CHOICES.map((choice) => (
              <option key={choice.value || "default"} value={choice.value}>
                {choice.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
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
