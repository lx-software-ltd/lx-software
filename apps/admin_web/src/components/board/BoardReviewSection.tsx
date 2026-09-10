import { useEffect, useState, type ReactNode } from "react";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import type { BoardReviewSnapshot } from "../../lib/boardModel";
import { BoardHoldsList } from "./BoardHoldsList";
import { useBoardHolds } from "../../hooks/useBoardHolds";
import { useBoardReview } from "../../hooks/useBoardReview";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

function Section({
  id,
  title,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly children: ReactNode;
}) {
  return (
    <section id={id} className="card shadow-sm mb-3">
      <div className="card-body">
        <h3 className="h6 mb-3">{title}</h3>
        {children}
      </div>
    </section>
  );
}

function Headline({ review }: { readonly review: BoardReviewSnapshot }) {
  const h = review.headline;
  const channels = Object.entries(h.messagesByChannel ?? {});
  return (
    <>
      {review.narrative ? <p className="mb-2">{review.narrative}</p> : <p className="text-muted small">No headline narrative yet.</p>}
      <div className="row g-2 small">
        <div className="col-auto">Delivered <strong>{h.tasks.delivered}</strong></div>
        <div className="col-auto">Running <strong>{h.tasks.running}</strong></div>
        <div className="col-auto">Blocked <strong>{h.tasks.blocked}</strong></div>
        <div className="col-auto">Holds executed/vetoed <strong>{h.holds.executed}/{h.holds.vetoed}</strong></div>
        <div className="col-auto">
          Staff spend <strong>{h.spend.staffUsd}</strong> / {h.spend.budgetUsd} USD
        </div>
      </div>
      {channels.length > 0 ? (
        <div className="small text-muted mt-2">
          Messages: {channels.map(([k, v]) => `${k} ${v}`).join(" · ")}
        </div>
      ) : null}
    </>
  );
}

export function BoardReviewSection() {
  const data = useBoardReview(true);
  const holds = useBoardHolds();
  const [wrongId, setWrongId] = useState<string | null>(null);
  const [wrongNote, setWrongNote] = useState("");
  const [showDigest, setShowDigest] = useState(false);

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    if (!hash) return;
    const el = document.getElementById(hash);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [data.review]);

  if (data.isLoading && !data.review) {
    return <p className="text-muted small">Compiling today&apos;s review…</p>;
  }
  if (data.isError) {
    return <div className="alert alert-danger py-2 small">{errorText(data.error)}</div>;
  }
  const review = data.review;
  if (!review) return null;

  return (
    <div>
      <div className="d-flex flex-wrap align-items-center gap-2 mb-3">
        <h2 className="h5 mb-0">Daily review</h2>
        <span className="small text-muted">{review.date}</span>
        <button type="button" className="btn btn-link btn-sm p-0" onClick={() => setShowDigest((v) => !v)}>
          {showDigest ? "Hide digest preview" : "Preview digest email"}
        </button>
      </div>
      {showDigest ? (
        <div className="border rounded p-3 mb-3 bg-body-tertiary small">
          {review.digestHtml ? (
            <div dangerouslySetInnerHTML={{ __html: review.digestHtml }} />
          ) : (
            <p className="mb-0 text-muted">
              Digest is emailed at 07:30 HKT to <code>settings.review.digestTo</code>. Section links
              match the headings on this page.
            </p>
          )}
        </div>
      ) : null}

      <Section id="headline" title="Headline numbers">
        <Headline review={review} />
      </Section>

      <Section id="holdsDue" title="On hold, executing soon">
        <BoardHoldsList
          holds={holds.holds}
          isLoading={holds.isLoading}
          isVetoing={holds.veto.isPending || holds.vetoClass.isPending}
          errorMessage={errorText(holds.veto.error) ?? errorText(holds.vetoClass.error)}
          onVeto={(holdId, reason) => holds.veto.mutate({ holdId, reason })}
          onVetoClass={(classKey) => holds.vetoClass.mutate(classKey)}
        />
      </Section>

      <Section id="escalations" title="Escalations">
        {review.escalations.length === 0 ? (
          <p className="text-muted small mb-0">None waiting.</p>
        ) : (
          <ul className="list-unstyled mb-0">
            {review.escalations.map((row) => (
              <li key={row.taskId} className="border-bottom py-2">
                <div className="fw-semibold">{row.brief}</div>
                <div className="small text-muted">{row.assignee}</div>
                {row.suggestedReply?.summary ? (
                  <div className="small mt-1">Suggested: {row.suggestedReply.summary}</div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="assisted" title="Assisted posts">
        <p className="text-muted small mb-0">Ready-to-post packs appear here after WP7.</p>
      </Section>

      <Section id="sample" title="Sample of what ran">
        {review.sample.length === 0 ? (
          <p className="text-muted small mb-0">No hold-0 actions yesterday.</p>
        ) : (
          <ul className="list-unstyled mb-0">
            {review.sample.map((row) => (
              <li key={row.callId} className="border-bottom py-2">
                <div>{row.summary || row.op}</div>
                {wrongId === row.callId ? (
                  <div className="mt-2">
                    <textarea
                      className="form-control form-control-sm mb-2"
                      rows={2}
                      value={wrongNote}
                      onChange={(ev) => setWrongNote(ev.target.value)}
                      placeholder="What should happen next time?"
                    />
                    <button
                      type="button"
                      className="btn btn-sm btn-primary me-2"
                      disabled={data.markWrong.isPending}
                      onClick={() =>
                        data.markWrong.mutate(
                          { callId: row.callId, note: wrongNote },
                          { onSuccess: () => { setWrongId(null); setWrongNote(""); } },
                        )
                      }
                    >
                      Save lesson draft
                    </button>
                    <button type="button" className="btn btn-sm btn-link" onClick={() => setWrongId(null)}>
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button type="button" className="btn btn-link btn-sm p-0" onClick={() => setWrongId(row.callId)}>
                    This was wrong
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {errorText(data.markWrong.error) ? (
          <div className="small text-danger mt-2">{errorText(data.markWrong.error)}</div>
        ) : null}
      </Section>

      <Section id="market" title="Market and ideas">
        {!review.market ? (
          <p className="text-muted small mb-0">No market notes yet.</p>
        ) : (
          <>
            {(review.market.changes ?? []).length === 0 ? (
              <p className="text-muted small mb-2">No watchlist changes this week.</p>
            ) : (
              <ul className="small mb-2">
                {(review.market.changes ?? []).slice(0, 8).map((c) => (
                  <li key={c.changeId}>{c.summary || c.url}</li>
                ))}
              </ul>
            )}
            {review.market.latestBrief ? (
              <p className="small mb-0">
                Latest brief: {review.market.latestBrief.summary || review.market.latestBrief.taskId}
              </p>
            ) : null}
          </>
        )}
      </Section>

      <Section id="breakers" title="Tripped breakers">
        {data.breakers.filter((b) => b.tripped).length === 0 ? (
          <p className="text-muted small mb-0">None tripped.</p>
        ) : (
          <ul className="list-unstyled mb-0">
            {data.breakers.filter((b) => b.tripped).map((b) => (
              <li key={b.name} className="d-flex justify-content-between align-items-start gap-2 py-1">
                <div>
                  <code>{b.name}</code>
                  <div className="small text-muted">{b.reason}</div>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-secondary"
                  disabled={data.resetBreaker.isPending}
                  onClick={() => data.resetBreaker.mutate(b.name)}
                >
                  Reset
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="suggestions" title="Boundary suggestions">
        {review.suggestions.length === 0 ? (
          <p className="text-muted small mb-0">No class is eligible to drop its hold yet.</p>
        ) : (
          <ul className="list-unstyled mb-0">
            {review.suggestions.map((row) => (
              <li key={row.classKey} className="d-flex justify-content-between align-items-center gap-2 py-1">
                <div>
                  <code>{row.classKey}</code>
                  <div className="small text-muted">
                    {row.actions} actions, {(row.rate * 100).toFixed(1)}% veto
                  </div>
                </div>
                <div className="btn-group btn-group-sm">
                  <button
                    type="button"
                    className="btn btn-outline-primary"
                    disabled={data.promote.isPending}
                    onClick={() => data.promote.mutate(row.classKey)}
                  >
                    Accept
                  </button>
                  <button type="button" className="btn btn-outline-secondary" disabled>
                    Later
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="promotion" title="Production promotion">
        <p className="text-muted small mb-0">Staging promotion lands in WP10.</p>
      </Section>
    </div>
  );
}
