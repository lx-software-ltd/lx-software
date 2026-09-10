import { useMemo, useState } from "react";
import { DateTimeDisplay } from "../ui";
import { MailPreviewCard } from "./BoardApprovalsList";
import { isMailPreview, type BoardHold } from "../../lib/boardModel";

export type BoardHoldsListProps = {
  readonly holds: readonly BoardHold[];
  readonly isLoading: boolean;
  readonly isVetoing: boolean;
  readonly errorMessage?: string | null;
  readonly onVeto: (holdId: string, reason: string) => void;
  readonly onVetoClass: (classKey: string) => void;
  readonly onOpenMailThread?: (threadId: string) => void;
};

function countdown(executeAt: string, nowMs: number): string {
  const when = Date.parse(executeAt);
  if (Number.isNaN(when)) return executeAt;
  const delta = when - nowMs;
  if (delta <= 0) return "due now";
  const hours = Math.floor(delta / 3_600_000);
  const minutes = Math.floor((delta % 3_600_000) / 60_000);
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ${hours % 24}h`;
  }
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${Math.max(1, minutes)}m`;
}

export function BoardHoldsList({
  holds,
  isLoading,
  isVetoing,
  errorMessage,
  onVeto,
  onVetoClass,
  onOpenMailThread,
}: BoardHoldsListProps) {
  const [nowMs] = useState(() => Date.now());
  const groups = useMemo(() => {
    const map = new Map<string, BoardHold[]>();
    for (const hold of holds) {
      const key = hold.classKey || hold.actionClass || "other";
      const list = map.get(key) ?? [];
      list.push(hold);
      map.set(key, list);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [holds]);

  return (
    <div className="card shadow-sm mb-4">
      <div className="card-body">
        <h2 className="h6 text-uppercase text-muted mb-2">Scheduled (veto to stop)</h2>
        <p className="text-muted small">
          These writes already passed the boundaries and will run at the time shown unless you veto.
          They are not Approvals: you do not need to say yes.
        </p>
        {errorMessage ? <div className="alert alert-danger py-2 small">{errorMessage}</div> : null}
        {isLoading ? <div className="text-muted small">Loading scheduled writes…</div> : null}
        {!isLoading && holds.length === 0 ? (
          <p className="text-muted small mb-0">Nothing is waiting out a hold window.</p>
        ) : null}
        {groups.map(([classKey, rows]) => (
          <div key={classKey} className="mb-3">
            <div className="d-flex justify-content-between align-items-center mb-1">
              <div className="small text-uppercase text-muted fw-semibold">{classKey}</div>
              <button
                type="button"
                className="btn btn-outline-danger btn-sm"
                disabled={isVetoing}
                onClick={() => onVetoClass(classKey)}
              >
                Veto all of this class today
              </button>
            </div>
            <ul className="list-group list-group-flush">
              {rows.map((hold) => (
                <li key={hold.holdId} className="list-group-item px-0">
                  <div className="d-flex justify-content-between gap-3">
                    <div className="min-w-0">
                      <div className="fw-semibold">{hold.summary || hold.op}</div>
                      <div className="small text-muted">
                        {hold.displayName || hold.personaId} · executes in {countdown(hold.executeAt, nowMs)} (
                        <DateTimeDisplay iso={hold.executeAt} />)
                      </div>
                      {isMailPreview(hold.preview) ? (
                        <div className="mt-2">
                          <MailPreviewCard preview={hold.preview} onOpenThread={onOpenMailThread} />
                        </div>
                      ) : hold.preview && "error" in hold.preview ? (
                        <div className="small text-muted mt-1">{hold.preview.error}</div>
                      ) : (
                        <pre className="small bg-body-tertiary rounded p-2 mt-2 mb-0">
                          {JSON.stringify(hold.arguments, null, 2)}
                        </pre>
                      )}
                    </div>
                    <button
                      type="button"
                      className="btn btn-outline-danger btn-sm align-self-start"
                      disabled={isVetoing}
                      onClick={() => onVeto(hold.holdId, "")}
                    >
                      Veto
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
