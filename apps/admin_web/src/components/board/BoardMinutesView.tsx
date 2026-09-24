import {
  memberLabel,
  PRIORITY_BADGE_CLASS,
  PRIORITY_LABELS,
  type BoardMember,
  type BoardMinutes,
} from "../../lib/boardModel";

export type BoardMinutesViewProps = {
  readonly minutes: BoardMinutes;
  readonly members: readonly Pick<BoardMember, "id" | "displayName" | "shortName">[];
  readonly createdActionCount: number;
  readonly reaffirmedActionCount: number;
};

const CONSENSUS_BADGE: Readonly<Record<string, string>> = {
  agree: "text-bg-success",
  split: "text-bg-warning",
  deferred: "text-bg-secondary",
};

const SEVERITY_BADGE: Readonly<Record<string, string>> = {
  high: "text-bg-danger",
  medium: "text-bg-warning",
  low: "text-bg-secondary",
};

export function BoardMinutesView({ minutes, members, createdActionCount, reaffirmedActionCount }: BoardMinutesViewProps) {
  return (
    <div className="board-minutes">
      {minutes.headline ? <p className="lead mb-3">{minutes.headline}</p> : null}

      {minutes.discussion.length > 0 ? (
        <section className="mb-3">
          <h3 className="admin-card-title">Discussion</h3>
          <ol className="mb-0 ps-3">
            {minutes.discussion.map((d, i) => {
              const agenda = minutes.agenda[d.agendaIndex - 1];
              return (
                <li key={i} className="mb-2">
                  <span className="fw-semibold">{agenda?.title ?? `Item ${d.agendaIndex}`}</span>{" "}
                  <span className={`badge ${CONSENSUS_BADGE[d.consensus] ?? "text-bg-secondary"}`}>{d.consensus}</span>
                  <div className="small">{d.summary}</div>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {minutes.decisions.length > 0 ? (
        <section className="mb-3">
          <h3 className="admin-card-title">Decisions</h3>
          <ul className="mb-0 ps-3">
            {minutes.decisions.map((d, i) => (
              <li key={i} className="mb-1">
                {d.text}
                <span className="small text-muted"> — {memberLabel(members, d.proposedBy)}{d.rationale ? `; ${d.rationale}` : ""}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {minutes.risks.length > 0 ? (
        <section className="mb-3">
          <h3 className="admin-card-title">Risks</h3>
          <ul className="list-unstyled mb-0">
            {minutes.risks.map((r, i) => (
              <li key={i} className="mb-1">
                <span className={`badge ${SEVERITY_BADGE[r.severity] ?? "text-bg-secondary"} me-2`}>{r.severity}</span>
                {r.text}
                <span className="small text-muted"> — {memberLabel(members, r.owner)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mb-3">
        <h3 className="admin-card-title">
          Actions for you
          <span className="fw-normal text-lowercase ms-2 small">
            {createdActionCount} new · {reaffirmedActionCount} re-raised
          </span>
        </h3>
        {minutes.actions.length === 0 ? (
          <p className="small text-muted mb-0">The board proposed no new actions.</p>
        ) : (
          <ol className="mb-0 ps-3">
            {minutes.actions.map((a, i) => (
              <li key={i} className="mb-2">
                <span className={`badge ${PRIORITY_BADGE_CLASS[a.priority] ?? "text-bg-secondary"} me-2`}>{PRIORITY_LABELS[a.priority] ?? a.priority}</span>
                <span className="fw-semibold">{a.title}</span>
                <div className="small text-muted">
                  {memberLabel(members, a.persona)} · effort {a.effort}
                  {a.dueInDays ? ` · due in ${a.dueInDays} days` : ""}
                  {a.existingActionId ? " · reaffirms an open action" : ""}
                </div>
                {a.detail ? <div className="small">{a.detail}</div> : null}
                {a.metric ? <div className="small text-muted">Success: {a.metric}</div> : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {minutes.questionsForOwner.length > 0 ? (
        <section>
          <h3 className="admin-card-title">Questions only you can answer</h3>
          <ul className="mb-0 ps-3">
            {minutes.questionsForOwner.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
