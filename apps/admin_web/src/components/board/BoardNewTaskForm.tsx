import { useState } from "react";
import { AdminEditorSection } from "../ui";
import type { BoardDeliverableType, BoardSeat, BoardTaskCreate } from "../../lib/boardModel";
import { BOARD_PERSONA_DEFAULTS, BOARD_STAFF_DELIVERABLE_TYPES } from "../../lib/contracts/generated";

export type BoardNewTaskFormProps = {
  readonly seats: readonly BoardSeat[];
  readonly disabled: boolean;
  readonly errorMessage?: string | null;
  readonly onCreate: (body: BoardTaskCreate) => void;
  readonly title?: string;
  readonly description?: string;
  readonly initialAssignee?: string;
  readonly initialBrief?: string;
  /** Founder action the task works on; sent as `actionId` so accepting the deliverable closes it. */
  readonly actionId?: string;
  readonly submitLabel?: string;
  readonly onCancel?: () => void;
  readonly idPrefix?: string;
  readonly embedded?: boolean;
};

export function BoardNewTaskForm({
  seats,
  disabled,
  errorMessage,
  onCreate,
  title = "New task",
  description = "Assign work to an executive or an active seat.",
  initialAssignee,
  initialBrief = "",
  actionId,
  submitLabel = "Create task",
  onCancel,
  idPrefix = "board-new-task",
  embedded = false,
}: BoardNewTaskFormProps) {
  const activeSeats = seats.filter((s) => s.isActive).map((s) => ({ id: s.id, label: `${s.displayName} · seat` }));
  const personas = BOARD_PERSONA_DEFAULTS.map((p) => ({ id: p.id, label: `${p.shortName} (${p.title})` }));
  const [assignee, setAssignee] = useState(initialAssignee ?? activeSeats[0]?.id ?? "cfo");
  const [brief, setBrief] = useState(initialBrief);
  const [deliverableType, setDeliverableType] = useState<BoardDeliverableType>("markdown");
  const assigneeId = `${idPrefix}-assignee`;
  const deliverableId = `${idPrefix}-deliverable`;
  const briefId = `${idPrefix}-brief`;
  return (
    <AdminEditorSection title={title} description={description} embedded={embedded}>
      <div className="row g-3">
        <div className="col-md-4">
          <label className="form-label small" htmlFor={assigneeId}>
            Assignee
          </label>
          <select id={assigneeId} className="form-select form-select-sm" value={assignee} onChange={(ev) => setAssignee(ev.target.value)}>
            {activeSeats.length ? (
              <optgroup label="Staff">
                {activeSeats.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </optgroup>
            ) : null}
            <optgroup label="Board">
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </optgroup>
          </select>
        </div>
        <div className="col-md-3">
          <label className="form-label small" htmlFor={deliverableId}>
            Deliverable
          </label>
          <select
            id={deliverableId}
            className="form-select form-select-sm"
            value={deliverableType}
            onChange={(ev) => setDeliverableType(ev.target.value as BoardDeliverableType)}
          >
            {BOARD_STAFF_DELIVERABLE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div className="col-12">
          <label className="form-label small" htmlFor={briefId}>
            Brief
          </label>
          <textarea id={briefId} className="form-control form-control-sm" rows={3} value={brief} onChange={(ev) => setBrief(ev.target.value)} />
        </div>
        <div className="col-12 d-flex align-items-center gap-2">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={disabled || !brief.trim()}
            onClick={() =>
              onCreate({
                assignee,
                brief: brief.trim(),
                deliverableType,
                slaHours: 24,
                ...(actionId ? { actionId } : {}),
              })
            }
          >
            {submitLabel}
          </button>
          {onCancel ? (
            <button type="button" className="btn btn-outline-secondary btn-sm" onClick={onCancel}>
              Cancel
            </button>
          ) : null}
          {errorMessage ? <span className="small text-danger">{errorMessage}</span> : null}
        </div>
      </div>
    </AdminEditorSection>
  );
}
