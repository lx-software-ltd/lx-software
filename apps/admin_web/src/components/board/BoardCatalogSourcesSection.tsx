import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { BOARD_CATALOG_LAUNCH_LISTING_TARGET } from "../../lib/contracts/generated";
import type { BoardCatalogJob } from "../../lib/boardModel";
import { useBoardCatalogCandidates, useBoardCatalogMutations, useBoardCatalogSources } from "../../hooks/useBoardCatalog";

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

function jobLine(job?: BoardCatalogJob | null): string | null {
  if (job?.phase !== "queued" && job?.phase !== "running") return null;
  const label =
    job.action === "import" ? "Import" : job.action === "preview" ? "Preview" : job.action === "ingest" ? "Ingest" : "Job";
  const progress =
    job.phase === "running" && job.offset != null && job.remaining != null
      ? ` ${job.offset} done, ${job.remaining} left`
      : "";
  return `${label} ${job.phase}${progress}…`;
}

function isJobBusy(phase?: string): boolean {
  return phase === "queued" || phase === "running";
}

export function BoardCatalogSourcesSection() {
  const sources = useBoardCatalogSources();
  const candidates = useBoardCatalogCandidates("new");
  const mutations = useBoardCatalogMutations();
  const rows = sources.data?.sources ?? [];
  const target = sources.data?.launchTarget ?? BOARD_CATALOG_LAUNCH_LISTING_TARGET;
  const queuedPreview = Boolean(mutations.preview.isSuccess && mutations.preview.data?.queued);
  const queuedImport = Boolean(mutations.importSource.isSuccess && mutations.importSource.data?.queued);
  const queuedScan = Boolean(mutations.runDiscovery.isSuccess && mutations.runDiscovery.data?.queued);
  return (
    <section className="card shadow-sm mb-3">
      <div className="card-body">
        <div className="d-flex flex-wrap align-items-end justify-content-between gap-2 mb-3">
          <div>
            <h3 className="h6 mb-1">Bulk catalog sources</h3>
            <p className="small text-muted mb-0">
              Preview then import official open data and Places. Launch gate is {target} live listings.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            disabled={mutations.runDiscovery.isPending}
            onClick={() => mutations.runDiscovery.mutate()}
          >
            {mutations.runDiscovery.isPending ? "Scanning…" : "Scan sources now"}
          </button>
        </div>
        {sources.isError ? <div className="alert alert-danger py-2 small">{errorText(sources.error)}</div> : null}
        {mutations.preview.isError ? (
          <div className="alert alert-danger py-2 small">{errorText(mutations.preview.error)}</div>
        ) : null}
        {mutations.importSource.isError ? (
          <div className="alert alert-danger py-2 small">{errorText(mutations.importSource.error)}</div>
        ) : null}
        {mutations.runDiscovery.isError ? (
          <div className="alert alert-danger py-2 small">{errorText(mutations.runDiscovery.error)}</div>
        ) : null}
        {queuedPreview || queuedImport || queuedScan ? (
          <div className="alert alert-info py-2 small">
            {queuedScan ? "Scan queued. " : null}
            {queuedPreview ? "Preview queued. " : null}
            {queuedImport ? "Import queued. " : null}
            This list refreshes every 30 seconds.
          </div>
        ) : null}
        {rows.length === 0 ? (
          <p className="small text-muted mb-0">No source rows yet. Scan or preview LCSD / EDB / SWD to fill the queue.</p>
        ) : (
          <table className="table table-sm mb-3">
            <thead>
              <tr>
                <th>Source</th>
                <th>New</th>
                <th>Approved</th>
                <th>Imported</th>
                <th className="visually-hidden">Operations</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="text-uppercase">
                    {row.id}
                    {jobLine(row.job) ? <div className="small text-muted">{jobLine(row.job)}</div> : null}
                    {row.job?.phase === "error" && row.job.error ? (
                      <div className="small text-danger">{row.job.error}</div>
                    ) : null}
                  </td>
                  <td>{row.counts.new ?? 0}</td>
                  <td>{row.counts.approved ?? 0}</td>
                  <td>{row.counts.imported ?? 0}</td>
                  <td className="text-end">
                    <button
                      type="button"
                      className="btn btn-outline-primary btn-sm me-1"
                      disabled={mutations.preview.isPending || isJobBusy(row.job?.phase)}
                      onClick={() => mutations.preview.mutate(row.id)}
                    >
                      Preview
                    </button>
                    <button
                      type="button"
                      className="btn btn-outline-secondary btn-sm"
                      disabled={
                        mutations.importSource.isPending ||
                        (row.counts.approved ?? 0) === 0 ||
                        isJobBusy(row.job?.phase)
                      }
                      onClick={() => {
                        const n = row.counts.approved ?? 0;
                        if (
                          !window.confirm(
                            `Import ${n} approved ${row.id} organisation${n === 1 ? "" : "s"} into the live catalog?`,
                          )
                        ) {
                          return;
                        }
                        mutations.importSource.mutate(row.id);
                      }}
                    >
                      Import
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <h4 className="h6">Competitor / Places candidates waiting on you</h4>
        {(candidates.data ?? []).length === 0 ? (
          <p className="small text-muted mb-0">No new candidates.</p>
        ) : (
          <ul className="list-unstyled small mb-0">
            {(candidates.data ?? []).slice(0, 12).map((row) => (
              <li key={row.candidateId} className="d-flex flex-wrap align-items-center gap-2 mb-1">
                <span>
                  {row.nameEn} · {row.district} · {row.source}
                </span>
                <button
                  type="button"
                  className="btn btn-outline-primary btn-sm"
                  disabled={mutations.decide.isPending}
                  onClick={() => mutations.decide.mutate({ candidateId: row.candidateId, decision: "approve" })}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm"
                  disabled={mutations.decide.isPending}
                  onClick={() => mutations.decide.mutate({ candidateId: row.candidateId, decision: "reject" })}
                >
                  Reject
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
