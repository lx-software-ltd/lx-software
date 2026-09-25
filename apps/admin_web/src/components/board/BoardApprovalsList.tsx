import { useEffect, useMemo, useState } from "react";
import { DateTimeDisplay } from "../ui";
import {
  APPROVAL_STATUS_BADGE_CLASS,
  approvalEditableFields,
  isMailPreview,
  isPhishingPreview,
  memberLabel,
  PHASE_LABELS,
  type BoardApproval,
  type BoardMailPreview,
  type BoardMember,
  type BoardPhishingPreview,
} from "../../lib/boardModel";
import { BOARD_MAX_APPROVAL_NOTE_LEN } from "../../lib/contracts/generated";
import type { ApprovalDecisionVariables } from "../../hooks/useBoardApprovals";
import { BoardCopyableId } from "./BoardCopyableId";

export type BoardApprovalsListProps = {
  readonly approvals: readonly BoardApproval[];
  readonly members: readonly BoardMember[];
  readonly isLoading: boolean;
  readonly isDeciding: boolean;
  readonly errorMessage?: string | null;
  readonly onDecide: (vars: ApprovalDecisionVariables) => void;
  readonly onOpenMeeting: (meetingId: string) => void;
  readonly onOpenMailThread?: (threadId: string) => void;
  /** Approval to scroll to and expand (from a "review" link in a chat or transcript). */
  readonly focusApprovalId?: string | null;
};

function formatArgValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(formatArgValue).join(", ");
  return JSON.stringify(value);
}

function ArgumentsTable({ args }: { readonly args: Readonly<Record<string, unknown>> }) {
  const entries = Object.entries(args).filter(([k]) => k !== "reason");
  if (entries.length === 0) return null;
  return (
    <table className="table table-sm table-borderless small admin-table-compact mb-0 board-approval-args">
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <th scope="row" className="text-muted fw-normal pe-3 ps-0 board-approval-arg-key">{k}</th>
            <td className="ps-0 board-approval-arg-value">{formatArgValue(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PhishingPreviewCard({ preview }: { readonly preview: BoardPhishingPreview }) {
  return (
    <div className="border rounded bg-body-tertiary p-2 small">
      <div className="fw-semibold">Suspected phishing</div>
      <div className="text-muted">{preview.mailbox} · {preview.from}</div>
      <div className="mt-1">{preview.subject || "(no subject)"}</div>
      {preview.note ? <pre className="mb-0 mt-1 board-mail-body">{preview.note}</pre> : null}
    </div>
  );
}

/** What the owner would actually send: real addresses, un-masked body. */
export function MailPreviewCard({ preview, onOpenThread }: { readonly preview: BoardMailPreview; readonly onOpenThread?: (threadId: string) => void }) {
  return (
    <div className="border rounded bg-body-tertiary p-2 small board-mail-preview">
      <div className="d-flex flex-wrap gap-3 text-muted">
        <span>
          <span className="text-uppercase fw-semibold me-1">from</span>
          <span className="text-body">{preview.from}</span>
        </span>
        <span>
          <span className="text-uppercase fw-semibold me-1">to</span>
          <span className="text-body">{preview.to.join(", ")}</span>
        </span>
        {preview.cc.length > 0 ? (
          <span>
            <span className="text-uppercase fw-semibold me-1">cc</span>
            <span className="text-body">{preview.cc.join(", ")}</span>
          </span>
        ) : null}
      </div>
      <div className="fw-semibold mt-1">{preview.subject}</div>
      <pre className="mb-0 mt-1 board-mail-body">{preview.text}</pre>
      <div className="d-flex flex-wrap gap-3 mt-2">
        {preview.threadId && onOpenThread ? (
          <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => onOpenThread(preview.threadId)}>
            open thread <i className="bi bi-arrow-right-short" aria-hidden="true" />
          </button>
        ) : null}
        {!preview.sendEnabled ? (
          <span className="text-warning-emphasis">
            <i className="bi bi-exclamation-triangle me-1" aria-hidden="true" />
            Sending is switched off for this deployment; approving records the decision but cannot send.
          </span>
        ) : null}
      </div>
    </div>
  );
}

export function BoardApprovalsList({
  approvals,
  members,
  isLoading,
  isDeciding,
  errorMessage,
  onDecide,
  onOpenMeeting,
  onOpenMailThread,
  focusApprovalId,
}: BoardApprovalsListProps) {
  const [showDecided, setShowDecided] = useState(false);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [editingArgsId, setEditingArgsId] = useState<string | null>(null);
  const [fieldDrafts, setFieldDrafts] = useState<Record<string, string>>({});
  const [rawJsonMode, setRawJsonMode] = useState(false);
  const [argsDraft, setArgsDraft] = useState("");
  const [argsError, setArgsError] = useState<string | null>(null);

  const pending = useMemo(() => approvals.filter((a) => a.status === "pending"), [approvals]);
  const decided = useMemo(
    () => approvals.filter((a) => a.status !== "pending").sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1)),
    [approvals],
  );

  // A "review" link may point at an already-decided approval; keep that list open so it can be scrolled to.
  const focusedIsDecided = decided.some((a) => a.approvalId === focusApprovalId);
  const isShowingDecided = showDecided || focusedIsDecided;

  useEffect(() => {
    if (!focusApprovalId) return;
    const el = document.getElementById(`board-approval-${focusApprovalId}`);
    el?.scrollIntoView({ block: "center" });
  }, [focusApprovalId, approvals.length]);

  const startEditArgs = (a: BoardApproval) => {
    setEditingArgsId(a.approvalId);
    const fields = approvalEditableFields(a.arguments, a.preview);
    setFieldDrafts(Object.fromEntries(fields.map((f) => [f.key, f.value])));
    setRawJsonMode(fields.length === 0);
    setArgsDraft(JSON.stringify(a.arguments, null, 2));
    setArgsError(null);
  };

  // Switching to raw JSON must carry the field edits along, not revert to the original.
  const switchToRawJson = (a: BoardApproval) => {
    setArgsDraft(JSON.stringify({ ...a.arguments, ...fieldDrafts }, null, 2));
    setArgsError(null);
    setRawJsonMode(true);
  };

  const approve = (a: BoardApproval) => {
    let override: Record<string, unknown> | undefined;
    if (editingArgsId === a.approvalId) {
      if (rawJsonMode) {
        try {
          const parsed: unknown = JSON.parse(argsDraft);
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Arguments must be a JSON object.");
          override = parsed as Record<string, unknown>;
        } catch (err) {
          setArgsError(err instanceof Error ? err.message : "Invalid JSON.");
          return;
        }
      } else {
        override = { ...a.arguments, ...fieldDrafts };
      }
    }
    onDecide({ approvalId: a.approvalId, decision: "approve", note: noteDrafts[a.approvalId], arguments: override });
    setEditingArgsId(null);
    setRawJsonMode(false);
  };

  const renderRow = (a: BoardApproval) => {
    const isPending = a.status === "pending";
    const isFocused = a.approvalId === focusApprovalId;
    return (
      <li
        key={a.approvalId}
        id={`board-approval-${a.approvalId}`}
        className={`list-group-item ${isFocused ? "board-approval-focus" : "px-0"}`}
      >
        <div className="d-flex flex-wrap align-items-center gap-2">
          <span className={`badge ${APPROVAL_STATUS_BADGE_CLASS[a.status] ?? "text-bg-secondary"}`}>{a.status}</span>
          <span className="badge text-bg-light border">{a.toolLabel}</span>
          <BoardCopyableId id={a.approvalId} noun="Approval" full />
          <span className="fw-semibold">{a.summary}</span>
        </div>
        <div className="small text-muted mt-1 d-flex flex-wrap gap-3">
          <span>
            <i className="bi bi-person" aria-hidden="true" /> {memberLabel(members, a.personaId)}
          </span>
          <span>
            <i className="bi bi-clock" aria-hidden="true" /> <DateTimeDisplay iso={a.createdAt} />
          </span>
          <span className="text-monospace">{a.op}</span>
          {a.context.meetingId ? (
            <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => onOpenMeeting(a.context.meetingId!)}>
              from meeting{a.context.phase ? ` (${PHASE_LABELS[a.context.phase] ?? a.context.phase})` : ""}
            </button>
          ) : (
            <span>from chat</span>
          )}
        </div>
        {a.reason ? (
          <div className="small mt-2">
            <span className="text-muted">Why: </span>
            {a.reason}
          </div>
        ) : null}
        {a.downgradeReason ? (
          <div className="small mt-1 text-warning-emphasis">
            <i className="bi bi-shield-lock me-1" aria-hidden="true" />
            Held for approval although the member may act: {a.downgradeReason}.
          </div>
        ) : null}

        {editingArgsId !== a.approvalId && isMailPreview(a.preview) ? (
          <div className="mt-2">
            <MailPreviewCard preview={a.preview} onOpenThread={onOpenMailThread} />
          </div>
        ) : null}
        {editingArgsId !== a.approvalId && isPhishingPreview(a.preview) ? (
          <div className="mt-2">
            <PhishingPreviewCard preview={a.preview} />
          </div>
        ) : null}
        {editingArgsId !== a.approvalId && a.preview && !isMailPreview(a.preview) && !isPhishingPreview(a.preview) && "error" in a.preview ? (
          <div className="small mt-2 text-danger">{a.preview.error}</div>
        ) : null}

        {editingArgsId === a.approvalId ? (
          <div className="mt-2">
            {!rawJsonMode ? (
              <>
                {approvalEditableFields(a.arguments, a.preview).map((field) => (
                  <label key={field.key} className="form-label small d-block mb-2">
                    {field.label}
                    {field.multiline ? (
                      <textarea
                        className="form-control form-control-sm mt-1"
                        rows={Math.min(10, Math.max(3, (fieldDrafts[field.key] ?? field.value).split("\n").length + 1))}
                        value={fieldDrafts[field.key] ?? field.value}
                        aria-label={`Edit ${field.label.toLowerCase()}`}
                        onChange={(ev) => setFieldDrafts((d) => ({ ...d, [field.key]: ev.target.value }))}
                      />
                    ) : (
                      <input
                        className="form-control form-control-sm mt-1"
                        value={fieldDrafts[field.key] ?? field.value}
                        aria-label={`Edit ${field.label.toLowerCase()}`}
                        onChange={(ev) => setFieldDrafts((d) => ({ ...d, [field.key]: ev.target.value }))}
                      />
                    )}
                  </label>
                ))}
                <button type="button" className="btn btn-link btn-sm p-0" onClick={() => switchToRawJson(a)}>
                  Edit raw JSON
                </button>
              </>
            ) : (
              <>
                <textarea
                  className={`form-control form-control-sm font-monospace ${argsError ? "is-invalid" : ""}`}
                  rows={Math.min(14, Math.max(4, argsDraft.split("\n").length))}
                  value={argsDraft}
                  aria-label="Edit the proposed arguments as JSON"
                  onChange={(ev) => setArgsDraft(ev.target.value)}
                />
                {argsError ? <div className="invalid-feedback d-block">{argsError}</div> : null}
              </>
            )}
          </div>
        ) : isMailPreview(a.preview) || isPhishingPreview(a.preview) ? null : (
          <div className="mt-2">
            <ArgumentsTable args={a.arguments} />
          </div>
        )}

        {isPending ? (
          <div className="mt-2 d-flex flex-column flex-md-row gap-2 align-items-md-start">
            <input
              className="form-control form-control-sm"
              value={noteDrafts[a.approvalId] ?? ""}
              maxLength={BOARD_MAX_APPROVAL_NOTE_LEN}
              placeholder="Optional note for the board (why you approved or rejected)"
              aria-label="Decision note"
              onChange={(ev) => setNoteDrafts((d) => ({ ...d, [a.approvalId]: ev.target.value }))}
            />
            <div className="d-flex flex-wrap gap-2">
              <button type="button" className="btn btn-sm btn-success" disabled={isDeciding} onClick={() => approve(a)}>
                <i className="bi bi-check2 me-1" aria-hidden="true" />
                {editingArgsId === a.approvalId ? "Approve edited" : "Approve"}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-outline-danger"
                disabled={isDeciding}
                onClick={() => onDecide({ approvalId: a.approvalId, decision: "reject", note: noteDrafts[a.approvalId] })}
              >
                Reject
              </button>
              {editingArgsId === a.approvalId ? (
                <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => setEditingArgsId(null)}>
                  Cancel edit
                </button>
              ) : (
                <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => startEditArgs(a)}>
                  Edit…
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="small text-muted mt-2 d-flex flex-wrap gap-3">
            {a.decidedAt ? (
              <span>
                decided <DateTimeDisplay iso={a.decidedAt} />
              </span>
            ) : null}
            {a.note ? (
              <span className="fst-italic">
                <i className="bi bi-chat-left-text" aria-hidden="true" /> {a.note}
              </span>
            ) : null}
            {a.errorMessage ? <span className="text-danger">{a.errorMessage}</span> : null}
            {a.result && typeof a.result.url === "string" ? (
              <a href={a.result.url} target="_blank" rel="noreferrer">
                open result <i className="bi bi-box-arrow-up-right" aria-hidden="true" />
              </a>
            ) : null}
          </div>
        )}
      </li>
    );
  };

  return (
    <div className="card shadow-sm mb-4">
      <div className="card-body">
        <div className="d-flex justify-content-end align-items-center mb-2">
          <div className="form-check form-switch mb-0 small">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-show-decided"
              checked={isShowingDecided}
              disabled={focusedIsDecided}
              onChange={(ev) => setShowDecided(ev.target.checked)}
            />
            <label className="form-check-label" htmlFor="board-show-decided">
              Show decided ({decided.length})
            </label>
          </div>
        </div>
        <p className="text-muted small">
          Members at the <strong>Propose</strong> level queue their writes here instead of doing them, and emails to
          anyone outside your allow-list land here even at <strong>Act</strong>. Approving runs the action exactly as
          shown (edit it first if you want to change it); rejecting tells the member why.
        </p>
        {errorMessage ? <div className="alert alert-danger py-2 small">{errorMessage}</div> : null}
        {isLoading ? (
          <div className="text-muted small">Loading approvals…</div>
        ) : pending.length === 0 ? (
          <p className="text-muted small mb-0">Nothing waiting for you.</p>
        ) : (
          <ul className="list-group list-group-flush">{pending.map(renderRow)}</ul>
        )}
        {isShowingDecided && decided.length > 0 ? (
          <div className="mt-3">
            <div className="small text-uppercase text-muted fw-semibold mb-1">Decided</div>
            <ul className="list-group list-group-flush">{decided.map(renderRow)}</ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
