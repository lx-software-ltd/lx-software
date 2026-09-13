import { useMemo, useState } from "react";
import { DateTimeDisplay, TableIconButton } from "../ui";
import { BoardNewTaskForm } from "./BoardNewTaskForm";
import {
  actionAssigneeLabel,
  actionTaskBrief,
  groupActionsByPriority,
  memberLabel,
  PRIORITY_BADGE_CLASS,
  PRIORITY_LABELS,
  type BoardAction,
  type BoardActionPriority,
  type BoardMember,
  type BoardSeat,
  type BoardTaskCreate,
} from "../../lib/boardModel";
import { BOARD_MAX_ACTION_NOTE_LEN } from "../../lib/contracts/generated";
import type { UpdateActionVariables } from "../../hooks/useBoardActions";

export type BoardActionsListProps = {
  readonly actions: readonly BoardAction[];
  readonly members: readonly BoardMember[];
  readonly isLoading: boolean;
  readonly onUpdate: (vars: UpdateActionVariables) => void;
  readonly onOpenMeeting: (meetingId: string) => void;
  /** Staff hand-off; omit (or pass `isStaffEnabled: false`) to hide the control. */
  readonly seats?: readonly BoardSeat[];
  readonly isStaffEnabled?: boolean;
  readonly isAssigning?: boolean;
  readonly assignErrorMessage?: string | null;
  readonly onAssignToStaff?: (body: BoardTaskCreate) => void;
  readonly onOpenStaffTask?: (taskId: string) => void;
};

const PRIORITY_ORDER: readonly BoardActionPriority[] = ["now", "next", "later"];

export function BoardActionsList({
  actions,
  members,
  isLoading,
  onUpdate,
  onOpenMeeting,
  seats = [],
  isStaffEnabled = false,
  isAssigning = false,
  assignErrorMessage,
  onAssignToStaff,
  onOpenStaffTask,
}: BoardActionsListProps) {
  const [showClosed, setShowClosed] = useState(false);
  const [noteDraftId, setNoteDraftId] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [assignDraftId, setAssignDraftId] = useState<string | null>(null);
  const [renderedAt] = useState(() => Date.now());
  const canAssign = isStaffEnabled && Boolean(onAssignToStaff);

  const open = useMemo(() => actions.filter((a) => a.status === "open"), [actions]);
  const closed = useMemo(
    () =>
      actions
        .filter((a) => a.status !== "open")
        .sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1)),
    [actions],
  );
  const grouped = useMemo(() => groupActionsByPriority(open), [open]);

  const startNote = (a: BoardAction) => {
    setNoteDraftId(a.actionId);
    setNoteDraft(a.note ?? "");
  };
  const saveNote = (a: BoardAction) => {
    onUpdate({ actionId: a.actionId, note: noteDraft.trim() });
    setNoteDraftId(null);
  };

  const renderRow = (a: BoardAction) => {
    const isDue = a.dueAt ? new Date(a.dueAt).getTime() < renderedAt : false;
    return (
      <li key={a.actionId} className="list-group-item px-0">
        <div className="d-flex gap-3 align-items-start">
          <div className="flex-grow-1">
            <div className="d-flex flex-wrap align-items-center gap-2">
              <span className={`badge ${PRIORITY_BADGE_CLASS[a.priority] ?? "text-bg-secondary"}`}>
                {PRIORITY_LABELS[a.priority] ?? a.priority}
              </span>
              <span className="badge text-bg-light border">{a.effort}</span>
              <span className={`fw-semibold ${a.status !== "open" ? "text-decoration-line-through text-muted" : ""}`}>
                {a.title}
              </span>
            </div>
            {a.detail ? <div className="small mt-1">{a.detail}</div> : null}
            <div className="small text-muted mt-1 d-flex flex-wrap gap-3">
              <span>
                <i className="bi bi-person" aria-hidden="true" /> {memberLabel(members, a.persona)}
              </span>
              {a.assignee ? (
                <span title="Working on it">
                  <i className="bi bi-people" aria-hidden="true" /> staff: {actionAssigneeLabel(members, seats, a.assignee)}
                  {a.staffTaskId && onOpenStaffTask ? (
                    <>
                      {" "}
                      <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => onOpenStaffTask(a.staffTaskId ?? "")}>
                        open task
                      </button>
                    </>
                  ) : null}
                </span>
              ) : null}
              {a.dueAt ? (
                <span className={isDue && a.status === "open" ? "text-danger" : ""}>
                  <i className="bi bi-calendar-event" aria-hidden="true" /> due <DateTimeDisplay iso={a.dueAt} />
                </span>
              ) : null}
              {a.metric ? (
                <span>
                  <i className="bi bi-speedometer2" aria-hidden="true" /> {a.metric}
                </span>
              ) : null}
              {a.reaffirmedByMeetingIds.length > 0 ? (
                <span title="Re-raised in later meetings">
                  <i className="bi bi-arrow-repeat" aria-hidden="true" /> raised {a.reaffirmedByMeetingIds.length + 1}×
                </span>
              ) : null}
              <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => onOpenMeeting(a.meetingId)}>
                from meeting
              </button>
            </div>
            {noteDraftId === a.actionId ? (
              <div className="mt-2 d-flex gap-2 align-items-start">
                <textarea
                  className="form-control form-control-sm"
                  rows={2}
                  value={noteDraft}
                  maxLength={BOARD_MAX_ACTION_NOTE_LEN}
                  placeholder="Your note (the board reads it next meeting)"
                  onChange={(ev) => setNoteDraft(ev.target.value)}
                />
                <button type="button" className="btn btn-sm btn-primary" onClick={() => saveNote(a)}>Save</button>
                <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => setNoteDraftId(null)}>Cancel</button>
              </div>
            ) : a.note ? (
              <div className="small mt-1 fst-italic">
                <i className="bi bi-chat-left-text" aria-hidden="true" /> {a.note}
              </div>
            ) : null}
            {assignDraftId === a.actionId && canAssign && onAssignToStaff ? (
              <div className="mt-2">
                <BoardNewTaskForm
                  seats={seats}
                  disabled={isAssigning}
                  errorMessage={assignErrorMessage}
                  title="Hand to staff"
                  description="The assignee works this action in the background; accepting the deliverable marks it done. Anything external still needs your approval."
                  initialBrief={actionTaskBrief(a)}
                  actionId={a.actionId}
                  submitLabel="Assign task"
                  idPrefix={`board-action-task-${a.actionId}`}
                  onCancel={() => setAssignDraftId(null)}
                  onCreate={(body) => {
                    onAssignToStaff(body);
                    setAssignDraftId(null);
                  }}
                />
              </div>
            ) : null}
          </div>
          <div className="text-nowrap">
            {a.status === "open" ? (
              <>
                {canAssign && !a.staffTaskId ? (
                  <TableIconButton iconClassName="bi bi-people" ariaLabel="Hand to staff" onClick={() => setAssignDraftId(a.actionId)} />
                ) : null}
                <TableIconButton iconClassName="bi bi-check2-circle" ariaLabel="Mark done" onClick={() => onUpdate({ actionId: a.actionId, status: "done" })} />
                <TableIconButton iconClassName="bi bi-x-circle" ariaLabel="Dismiss" variant="danger" onClick={() => onUpdate({ actionId: a.actionId, status: "dismissed" })} />
              </>
            ) : (
              <TableIconButton iconClassName="bi bi-arrow-counterclockwise" ariaLabel="Reopen" onClick={() => onUpdate({ actionId: a.actionId, status: "open" })} />
            )}
            <TableIconButton iconClassName="bi bi-pencil" ariaLabel="Add a note" onClick={() => startNote(a)} />
          </div>
        </div>
      </li>
    );
  };

  return (
    <div className="card shadow-sm mb-4">
      <div className="card-body">
        <div className="d-flex justify-content-between align-items-center mb-2">
          <h2 className="h6 text-uppercase text-muted mb-0">Next actions</h2>
          <div className="form-check form-switch mb-0 small">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-show-closed"
              checked={showClosed}
              onChange={(ev) => setShowClosed(ev.target.checked)}
            />
            <label className="form-check-label" htmlFor="board-show-closed">
              Show completed ({closed.length})
            </label>
          </div>
        </div>
        {isLoading ? (
          <div className="text-muted small">Loading actions…</div>
        ) : open.length === 0 ? (
          <p className="text-muted small mb-0">
            No open actions. Run a meeting and the board will hand you a prioritised list.
          </p>
        ) : (
          PRIORITY_ORDER.map((priority) =>
            grouped[priority].length > 0 ? (
              <div key={priority} className="mb-3">
                <div className="small text-uppercase text-muted fw-semibold mb-1">
                  {PRIORITY_LABELS[priority]} · {grouped[priority].length}
                </div>
                <ul className="list-group list-group-flush">{grouped[priority].map(renderRow)}</ul>
              </div>
            ) : null,
          )
        )}
        {showClosed && closed.length > 0 ? (
          <div className="mt-3">
            <div className="small text-uppercase text-muted fw-semibold mb-1">Completed or dismissed</div>
            <ul className="list-group list-group-flush">{closed.map(renderRow)}</ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
