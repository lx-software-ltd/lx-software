import { useEffect, useState, type ReactNode } from "react";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import type { BoardContentItem, BoardReviewSnapshot } from "../../lib/boardModel";
import { BoardHoldsList } from "./BoardHoldsList";
import { useBoardContent } from "../../hooks/useBoardContent";
import { useBoardHolds } from "../../hooks/useBoardHolds";
import { BOARD_CODE_CI_FIX_MAX_ROUNDS } from "../../lib/contracts/generated";
import { useBoardReview } from "../../hooks/useBoardReview";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

function Section({
  id,
  title,
  children,
  lane = "main",
}: {
  readonly id: string;
  readonly title: string;
  readonly children: ReactNode;
  readonly lane?: "main" | "aside";
}) {
  return (
    <section id={id} data-lane={lane} className="card shadow-sm mb-3">
      <div className="card-body">
        <h3 className="admin-card-title">{title}</h3>
        {children}
      </div>
    </section>
  );
}

function AssistedPosts({ items }: { readonly items: readonly BoardContentItem[] }) {
  const calendar = useBoardContent();
  const rows = items ?? [];
  return (
    <Section id="assisted" title="Assisted posts">
      {rows.length > 0 ? (
        <ul className="list-unstyled mb-0">
          {rows.map((item) => (
            <li key={item.contentId} className="border-bottom py-2">
              <div className="small fw-semibold">{item.channel} · {item.slotAt?.slice(0, 16)}</div>
              <div className="small">{item.copyZh || item.copyEn}</div>
              <button
                type="button"
                className="btn btn-sm btn-outline-primary mt-1"
                disabled={calendar.update.isPending}
                onClick={() => calendar.update.mutate({ contentId: item.contentId, body: { status: "published" } })}
              >
                Mark posted
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted small mb-0">No assisted packs are due.</p>
      )}
    </Section>
  );
}

function StagingPromote({ data }: { readonly data: ReturnType<typeof useBoardReview> }) {
  const staging = data.staging;
  const commits = staging?.commits ?? [];
  const behind = staging?.behindBy ?? 0;
  const ahead = staging?.aheadBy ?? 0;
  const syncOnly = Boolean(staging?.syncOnly);
  const showSync = behind > 0 || syncOnly;
  return (
    <div>
      {staging?.error ? <p className="text-danger small">{staging.error}</p> : null}
      {behind > 0 ? (
        <p className="small text-warning">
          staging is {behind} commit(s) behind main
          {ahead > 0 && !syncOnly ? " and has commits of its own" : ""}
          {syncOnly ? "; the commits ahead are only sync merges" : ""}. Merge main into staging before promoting.
        </p>
      ) : null}
      {behind === 0 && syncOnly ? (
        <p className="small text-warning">Only sync merges are ahead of main. Reset staging to main before promoting.</p>
      ) : null}
      {commits.length === 0 ? (
        <p className="text-muted small mb-2">No staging commits ahead of main.</p>
      ) : (
        <ul className="small mb-3">
          {commits.map((c) => (
            <li key={c.sha || c.message}>
              <code>{c.sha}</code> {c.message}
            </li>
          ))}
        </ul>
      )}
      <div className="d-flex flex-wrap gap-2">
        {showSync ? (
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            disabled={data.syncStaging.isPending}
            onClick={() => data.syncStaging.mutate()}
          >
            Sync from main
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={data.promoteStaging.isPending || !staging?.canPromote}
          onClick={() => data.promoteStaging.mutate()}
        >
          Promote
        </button>
      </div>
      {data.syncStaging.isSuccess ? (
        <p className="small text-muted mt-2 mb-0">
          {data.syncStaging.data?.reset
            ? "Reset staging to main."
            : data.syncStaging.data?.fastForward
              ? "Fast-forwarded staging to main."
              : data.syncStaging.data?.alreadyCurrent
                ? "Staging already matches main."
                : "Merged main into staging."}
        </p>
      ) : null}
      {data.syncStaging.isError ? (
        <p className="small text-danger mt-2 mb-0">{errorText(data.syncStaging.error)}</p>
      ) : null}
      {data.promoteStaging.isSuccess ? (
        <p className="small text-muted mt-2 mb-0">Queued an Approval. Confirm it under Approvals to open the staging→main PR.</p>
      ) : null}
      {data.promoteStaging.isError ? (
        <p className="small text-danger mt-2 mb-0">{errorText(data.promoteStaging.error)}</p>
      ) : null}
    </div>
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
        {h.mail ? (
          <div className="col-auto">
            Mail: <strong>{h.mail.replied}</strong> replied / <strong>{h.mail.archived}</strong> archived /{" "}
            <strong>{h.mail.open}</strong> open
          </div>
        ) : null}
        <div className="col-auto">Holds executed/vetoed <strong>{h.holds.executed}/{h.holds.vetoed}</strong></div>
        <div className="col-auto">
          Staff spend <strong>{h.spend.staffUsd}</strong> / {h.spend.budgetUsd} USD
        </div>
        {h.catalog && (h.catalog.importedDistricts || h.catalog.nextDistrict) ? (
          <div className="col-auto">
            Catalog: <strong>{h.catalog.importedDistricts ?? 0}</strong> imported,{" "}
            <strong>{h.catalog.completeDistricts ?? 0}</strong> ≥ 50%
            {h.catalog.nextDistrict ? <> · next {h.catalog.nextDistrict}</> : null}
            {h.catalog.revalidateExhausted ? (
              <> · {h.catalog.revalidateExhausted} automatic retries exhausted</>
            ) : null}
          </div>
        ) : null}
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
    <div className="admin-review">
      <div className="admin-review-header d-flex flex-wrap align-items-center gap-2 mb-3">
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
              Digest is emailed at 07:30 HKT to <code>settings.review.digestTo</code>. The mail
              includes the same section summaries as this page (not links).
            </p>
          )}
        </div>
      ) : null}

      <Section id="headline" title="Headline numbers">
        <Headline review={review} />
      </Section>

      <Section id="holdsDue" title="On hold, executing soon" lane="aside">
        <BoardHoldsList
          holds={holds.holds}
          isLoading={holds.isLoading}
          isVetoing={holds.veto.isPending || holds.vetoClass.isPending}
          errorMessage={errorText(holds.veto.error) ?? errorText(holds.vetoClass.error)}
          onVeto={(holdId, reason) => holds.veto.mutate({ holdId, reason })}
          onVetoClass={(classKey) => holds.vetoClass.mutate(classKey)}
        />
      </Section>

      <Section id="escalations" title="Escalations" lane="aside">
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

      <AssistedPosts items={review.assisted ?? []} />

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

      <Section id="suggestions" title="Boundary suggestions" lane="aside">
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

      <Section id="configGaps" title="Unconfigured integrations">
        {(review.configGaps ?? []).length === 0 ? (
          <p className="text-muted small mb-0">None.</p>
        ) : (
          <ul className="list-unstyled mb-0">
            {(review.configGaps ?? []).map((row) => (
              <li key={`${row.gapId || "gap"}-${row.week || row.at || ""}`} className="border-bottom py-2">
                <div className="small fw-semibold">{row.gapId}</div>
                <div className="small">{row.reason}</div>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="dmarc" title="DMARC">
        <p className="small mb-2">
          {review.dmarc?.line || "DMARC (reports received in the last 24 h): no summary yet."}
        </p>
        {(review.dmarc?.findings ?? []).length > 0 ? (
          <ul className="small mb-0">
            {(review.dmarc?.findings ?? []).slice(0, 8).map((finding) => (
              <li key={finding.fingerprint || finding.summary}>
                {finding.severity ? `${finding.severity}: ` : ""}
                {finding.summary}
              </li>
            ))}
          </ul>
        ) : null}
      </Section>

      <Section id="engineering" title="Engineering">
        {(review.engineering ?? []).length === 0 ? (
          <p className="text-muted small mb-0">No open board pull requests.</p>
        ) : (
          <ul className="list-unstyled mb-0">
            {(review.engineering ?? []).map((row) => (
              <li key={`${row.taskId || "run"}-${row.prNumber || ""}`} className="border-bottom py-2">
                <div className="small fw-semibold">
                  PR #{row.prNumber} CI {row.ciState || "unknown"}
                  {row.ciState === "failure"
                    ? ` (ci-fix ${row.ciFixRounds ?? 0}/${row.ciFixMax ?? BOARD_CODE_CI_FIX_MAX_ROUNDS})`
                    : ""}
                </div>
                {row.failureLine ? <div className="small">{row.failureLine}</div> : null}
                {row.canRevise === false ? (
                  <div className="small text-muted">Runner cannot revise — apply the Appendix A revision patch.</div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="promotion" title="Production promotion" lane="aside">
        <StagingPromote data={data} />
      </Section>
    </div>
  );
}
