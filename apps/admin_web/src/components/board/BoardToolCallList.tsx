import { TOOL_CALL_STATUS_ICON, type BoardToolCallRef } from "../../lib/boardModel";

export type BoardToolCallListProps = {
  readonly calls: readonly BoardToolCallRef[];
  /** Adds a spinner row while the reply is still being generated. */
  readonly isLive?: boolean;
  readonly onOpenApproval?: (approvalId: string) => void;
  readonly className?: string;
};

/** Compact "what this member looked up or proposed" list under a chat reply or transcript turn. */
export function BoardToolCallList({ calls, isLive, onOpenApproval, className }: BoardToolCallListProps) {
  if (calls.length === 0 && !isLive) return null;
  return (
    <ul className={`board-tool-calls list-unstyled mb-0 ${className ?? ""}`}>
      {calls.map((c) => {
        const status = TOOL_CALL_STATUS_ICON[c.status] ?? TOOL_CALL_STATUS_ICON.error;
        return (
          <li key={c.callId} className="d-flex align-items-start gap-2">
            <i className={`bi ${status.icon} ${status.className} flex-shrink-0`} role="img" aria-label={status.label} />
            <span className="min-w-0">
              <span className={`badge rounded-pill ${c.kind === "write" ? "text-bg-warning" : "text-bg-light border text-muted"} me-1`}>
                {c.toolLabel}
              </span>
              <span>{c.summary}</span>
              {c.error ? <span className="text-danger"> — {c.error}</span> : null}
              {c.status === "pending_approval" && c.approvalId && onOpenApproval ? (
                <>
                  {" "}
                  <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => onOpenApproval(c.approvalId!)}>
                    review
                  </button>
                </>
              ) : null}
            </span>
          </li>
        );
      })}
      {isLive ? (
        <li className="d-flex align-items-center gap-2 text-muted">
          <span className="spinner-border spinner-border-sm" aria-hidden="true" />
          <span>{calls.length > 0 ? "Thinking about what it found…" : "Thinking…"}</span>
        </li>
      ) : null}
    </ul>
  );
}
