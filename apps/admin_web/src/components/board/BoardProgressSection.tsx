import type { ReactNode } from "react";
import { useBoardProgress } from "../../hooks/useBoardProgress";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import type { BoardProgressSnapshot } from "../../lib/boardModel";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `${Math.round(value * 100)}%`;
}

export function BoardProgressSection({
  onOpenSection,
}: {
  readonly onOpenSection?: (section: string) => void;
}) {
  const query = useBoardProgress();
  if (query.isLoading && !query.data) {
    return <p className="text-muted small">Loading listing and partnership progress…</p>;
  }
  if (query.isError) {
    return <div className="alert alert-danger py-2 small">{errorText(query.error)}</div>;
  }
  const snap = query.data;
  if (!snap) return null;
  return <ProgressBody snap={snap} onOpenSection={onOpenSection} />;
}

function ProgressBody({
  snap,
  onOpenSection,
}: {
  readonly snap: BoardProgressSnapshot;
  readonly onOpenSection?: (section: string) => void;
}) {
  const listings = snap.listings;
  const signings = snap.signings;
  const partnerships = snap.partnerships;
  const content = snap.content;
  const warm = partnerships.qualifiedThisWeek;
  const target = partnerships.weeklyTarget || 15;
  return (
    <div>
      <div className="d-flex flex-wrap align-items-end justify-content-between gap-2 mb-3">
        <div>
          <h2 className="h5 mb-1">Progress</h2>
          <p className="small text-muted mb-0">
            Live catalog, vendor onboarding and outreach, plus the next week of content. Refreshes every 30 seconds.
          </p>
        </div>
        <span className="small text-muted">Updated {snap.fetchedAt.replace("T", " ").replace("Z", " UTC")}</span>
      </div>

      <div className="row g-3 mb-3">
        <Kpi
          label="Live listings"
          value={String(listings.activities)}
          hint={
            listings.error
              ? listings.error
              : `${listings.providers} providers · completeness ${pct(listings.completenessAvg)} · photo ${pct(listings.hasPhotoAvg)} · price ${pct(listings.hasPriceAvg)} · hours ${pct(listings.hasScheduleAvg)} · geo ${pct(listings.hasGeoAvg)}`
          }
        />
        <Kpi
          label="Listing views (7d)"
          value={String(listings.funnel7d.listingViews)}
          hint={`${listings.funnel7d.leads} leads · ${listings.funnel7d.bookings} bookings`}
        />
        <Kpi
          label="Vendor signings"
          value={String(signings.count)}
          hint={signings.error ? signings.error : `${signings.stalled.length} idle ≥ 7 days`}
        />
        <Kpi
          label="Partnerships this week"
          value={`${warm} / ${target}`}
          hint={`${partnerships.needsContact} still need a contact`}
        />
        <Kpi
          label="Content next 7 days"
          value={String(content.scheduledNext7)}
          hint={content.emptyChannels.length ? `Empty: ${content.emptyChannels.join(", ")}` : "Channels have slots"}
        />
      </div>

      <div className="progress mb-3" role="img" aria-label="Partnerships versus weekly target">
        <div className="progress-bar" style={{ width: `${Math.min(100, Math.round((warm / Math.max(target, 1)) * 100))}%` }} />
      </div>

      {snap.bottlenecks.length ? (
        <div className="alert alert-warning py-2 small mb-4">
          <div className="fw-semibold mb-1">Bottlenecks</div>
          <ul className="mb-0 ps-3">
            {snap.bottlenecks.map((row) => (
              <li key={row.id}>
                {row.summary}{" "}
                {onOpenSection ? (
                  <button
                    type="button"
                    className="btn btn-link btn-sm p-0 align-baseline"
                    onClick={() => onOpenSection(row.section)}
                  >
                    {row.section === "progress" ? "this view" : row.section}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="small text-muted">No bottlenecks in the current snapshot.</p>
      )}

      <div className="row g-3">
        <div className="col-12 col-xl-6">
          <Panel title="Listings by district">
            {listings.byDistrict.length === 0 ? (
              <p className="small text-muted mb-0">{listings.error || "Catalog health is empty."}</p>
            ) : (
              <table className="table table-sm mb-0">
                <thead>
                  <tr>
                    <th>District</th>
                    <th>Listings</th>
                    <th className="d-none d-md-table-cell">Providers</th>
                    <th className="d-none d-md-table-cell">Complete</th>
                    <th className="d-none d-lg-table-cell">Photo</th>
                    <th className="d-none d-lg-table-cell">Price</th>
                    <th className="d-none d-lg-table-cell">Hours</th>
                    <th className="d-none d-lg-table-cell">Geo</th>
                  </tr>
                </thead>
                <tbody>
                  {listings.byDistrict.map((row) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td>{row.activities}</td>
                      <td className="d-none d-md-table-cell">{row.providers}</td>
                      <td className="d-none d-md-table-cell">{pct(row.completenessAvg)}</td>
                      <td className="d-none d-lg-table-cell">{pct(row.hasPhotoAvg)}</td>
                      <td className="d-none d-lg-table-cell">{pct(row.hasPriceAvg)}</td>
                      <td className="d-none d-lg-table-cell">{pct(row.hasScheduleAvg)}</td>
                      <td className="d-none d-lg-table-cell">{pct(row.hasGeoAvg)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
        <div className="col-12 col-xl-6">
          <Panel title="Stalled vendor onboarding">
            {signings.stalled.length === 0 ? (
              <p className="small text-muted mb-0">{signings.error || "No idle onboarding."}</p>
            ) : (
              <table className="table table-sm mb-0">
                <thead>
                  <tr>
                    <th>Provider</th>
                    <th>Step</th>
                    <th className="d-none d-md-table-cell">Idle days</th>
                  </tr>
                </thead>
                <tbody>
                  {signings.stalled.map((row) => (
                    <tr key={row.id || row.name}>
                      <td>{row.name}</td>
                      <td>{row.step}</td>
                      <td className="d-none d-md-table-cell">{row.daysSinceLastEdit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
        <div className="col-12 col-xl-6">
          <Panel title="Stalled outreach">
            {partnerships.stalled.length === 0 ? (
              <p className="small text-muted mb-0">No overdue outreach touches.</p>
            ) : (
              <table className="table table-sm mb-0">
                <thead>
                  <tr>
                    <th>Prospect</th>
                    <th>Stage</th>
                    <th className="d-none d-md-table-cell">District</th>
                  </tr>
                </thead>
                <tbody>
                  {partnerships.stalled.map((row) => (
                    <tr key={row.id || row.name}>
                      <td>{row.name}</td>
                      <td>{row.stage}</td>
                      <td className="d-none d-md-table-cell">{row.district || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
        <div className="col-12 col-xl-6">
          <Panel title="Content sitting in draft">
            {content.stalledDrafts.length === 0 ? (
              <p className="small text-muted mb-0">No stale drafts.</p>
            ) : (
              <table className="table table-sm mb-0">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th>Channel</th>
                    <th className="d-none d-md-table-cell">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {content.stalledDrafts.map((row) => (
                    <tr key={row.id}>
                      <td>{row.title}</td>
                      <td>{row.channel}</td>
                      <td className="d-none d-md-table-cell">{row.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

function Panel({ title, children }: { readonly title: string; readonly children: ReactNode }) {
  return (
    <section className="card shadow-sm h-100">
      <div className="card-body">
        <h3 className="h6 mb-3">{title}</h3>
        {children}
      </div>
    </section>
  );
}

function Kpi({ label, value, hint }: { readonly label: string; readonly value: string; readonly hint: string }) {
  return (
    <div className="col-6 col-md">
      <div className="card shadow-sm h-100">
        <div className="card-body py-2">
          <div className="small text-muted text-uppercase">{label}</div>
          <div className="fs-5 fw-semibold">{value}</div>
          <div className="small text-muted">{hint}</div>
        </div>
      </div>
    </div>
  );
}
