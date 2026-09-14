import { BoardMarkdown } from "./BoardMarkdown";
import { BoardToolCallList } from "./BoardToolCallList";
import { formatUsageCost, memberInitials, PHASE_LABELS, type BoardTurn } from "../../lib/boardModel";

export type BoardTranscriptProps = {
  readonly turns: readonly BoardTurn[];
  readonly isRunning: boolean;
  readonly currentPhaseLabel: string;
  readonly onOpenApproval?: (approvalId: string) => void;
};

export function BoardTranscript({ turns, isRunning, currentPhaseLabel, onOpenApproval }: BoardTranscriptProps) {
  return (
    <div className="board-transcript">
      {turns.map((t, i) => {
        const showPhase = i === 0 || turns[i - 1].phase !== t.phase;
        const toolCalls = t.kind === "tool" ? t.data?.calls ?? [] : [];
        return (
          <div key={t.seq}>
            {showPhase ? (
              <div className="small text-uppercase text-muted fw-semibold mt-3 mb-2 border-bottom pb-1">
                {PHASE_LABELS[t.phase] ?? t.phase}
              </div>
            ) : null}
            <div className="d-flex gap-3 mb-3">
              <div className="board-avatar board-avatar-sm flex-shrink-0" aria-hidden="true">
                {memberInitials({ displayName: t.displayName, shortName: t.personaId.toUpperCase() })}
              </div>
              <div className="flex-grow-1 min-w-0">
                <div className="small">
                  <span className="fw-semibold">{t.displayName}</span>
                  <span className="text-muted"> · {t.title}</span>
                  {t.usage ? <span className="text-muted"> · {formatUsageCost(t.usage.cost)}</span> : null}
                  {t.model ? <span className="text-muted"> · {t.model}</span> : null}
                </div>
                {t.kind === "tool" ? (
                  toolCalls.length > 0 ? (
                    <details className="small text-muted board-transcript-tools">
                      <summary>
                        <i className="bi bi-tools me-1" aria-hidden="true" />
                        {t.displayName} looked at {toolCalls.length} thing{toolCalls.length === 1 ? "" : "s"}
                      </summary>
                      <BoardToolCallList calls={toolCalls} onOpenApproval={onOpenApproval} className="mt-1" />
                    </details>
                  ) : (
                    <BoardMarkdown text={t.text} className="small text-muted" />
                  )
                ) : (
                  <BoardMarkdown text={t.text} className="small" />
                )}
              </div>
            </div>
          </div>
        );
      })}
      {isRunning ? (
        <div className="d-flex align-items-center gap-2 text-muted small mt-2" aria-live="polite">
          <span className="spinner-border spinner-border-sm" aria-hidden="true" />
          {currentPhaseLabel}…
        </div>
      ) : turns.length === 0 ? (
        <p className="small text-muted mb-0">No transcript.</p>
      ) : null}
    </div>
  );
}
