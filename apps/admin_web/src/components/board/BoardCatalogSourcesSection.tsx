import { useEffect, useMemo, useState } from "react";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { BOARD_CATALOG_BULK_SOURCES, BOARD_CATALOG_DISTRICTS, BOARD_CATALOG_LAUNCH_LISTING_TARGET } from "../../lib/contracts/generated";
import type { BoardCatalogJob } from "../../lib/boardModel";
import { useBoardCatalogCandidates, useBoardCatalogMutations, useBoardCatalogSources } from "../../hooks/useBoardCatalog";
import { AdminCell, AdminDataTable, AdminDataTableEmptyRow, TableIconButton } from "../ui";

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

function competitorCutoffIso(): string {
  return new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
}

const CANDIDATE_FILTER_DEBOUNCE_MS = 300;

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(handle);
  }, [value, delayMs]);
  return debounced;
}

const CANDIDATE_COLUMNS = [
  { key: "name", header: "Name" },
  { key: "district", header: "District", priority: "secondary" as const },
  { key: "source", header: "Source", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
];

export function BoardCatalogSourcesSection() {
  const sources = useBoardCatalogSources();
  const [sourceFilter, setSourceFilter] = useState("");
  const [districtFilter, setDistrictFilter] = useState("");
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, CANDIDATE_FILTER_DEBOUNCE_MS);
  const filters = useMemo(
    () => ({
      status: "new",
      source: sourceFilter || undefined,
      district: districtFilter || undefined,
      q: debouncedQuery || undefined,
    }),
    [sourceFilter, districtFilter, debouncedQuery],
  );
  const candidates = useBoardCatalogCandidates(filters);
  const mutations = useBoardCatalogMutations();
  const rows = sources.data?.sources ?? [];
  const target = sources.data?.launchTarget ?? BOARD_CATALOG_LAUNCH_LISTING_TARGET;
  const queuedPreview = Boolean(mutations.preview.isSuccess && mutations.preview.data?.queued);
  const queuedImport = Boolean(mutations.importSource.isSuccess && mutations.importSource.data?.queued);
  const queuedScan = Boolean(mutations.runDiscovery.isSuccess && mutations.runDiscovery.data?.queued);
  const candidateRows = candidates.data ?? [];
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
          <div className="table-responsive">
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
                    {row.job?.error && (row.job.phase === "error" || row.job.ok === false) ? (
                      <div className="small text-danger">
                        {row.job.phase === "done" ? "Finished with errors: " : null}
                        {row.job.error}
                      </div>
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
          </div>
        )}
        <div className="d-flex flex-wrap align-items-end justify-content-between gap-2 mb-2">
          <h4 className="h6 mb-0">Competitor / Places candidates waiting on you</h4>
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm"
            disabled={mutations.bulkDecide.isPending}
            onClick={() => {
              if (
                !window.confirm(
                  "Close leftover competitor candidates that are still new, have no Places match, and are older than 7 days?",
                )
              ) {
                return;
              }
              mutations.bulkDecide.mutate({
                decision: "close",
                source: "competitor",
                status: "new",
                before: competitorCutoffIso(),
                missingPlaceId: true,
              });
            }}
          >
            {mutations.bulkDecide.isPending ? "Closing…" : "Close leftover competitors"}
          </button>
        </div>
        {mutations.decide.isError ? (
          <div className="alert alert-danger py-2 small">{errorText(mutations.decide.error)}</div>
        ) : null}
        {mutations.bulkDecide.isError ? (
          <div className="alert alert-danger py-2 small">{errorText(mutations.bulkDecide.error)}</div>
        ) : null}
        {mutations.bulkDecide.isSuccess && mutations.bulkDecide.data ? (
          <div className="alert alert-info py-2 small">
            Updated {mutations.bulkDecide.data.updated} candidate
            {mutations.bulkDecide.data.updated === 1 ? "" : "s"}.
          </div>
        ) : null}
        <div className="row g-2 mb-2">
          <div className="col-md-4">
            <label className="form-label small mb-1" htmlFor="catalog-cand-source">
              Source
            </label>
            <select
              id="catalog-cand-source"
              className="form-select form-select-sm"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
            >
              <option value="">All</option>
              {BOARD_CATALOG_BULK_SOURCES.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </div>
          <div className="col-md-4">
            <label className="form-label small mb-1" htmlFor="catalog-cand-district">
              District
            </label>
            <select
              id="catalog-cand-district"
              className="form-select form-select-sm"
              value={districtFilter}
              onChange={(e) => setDistrictFilter(e.target.value)}
            >
              <option value="">All</option>
              {BOARD_CATALOG_DISTRICTS.map((row) => (
                <option key={row.id} value={row.name}>
                  {row.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <AdminDataTable
          columns={CANDIDATE_COLUMNS}
          filterValue={query}
          onFilterChange={setQuery}
          filterPlaceholder="Filter candidates"
          embedded
        >
          {candidateRows.length === 0 ? (
            <AdminDataTableEmptyRow colSpan={CANDIDATE_COLUMNS.length} message="No new candidates." />
          ) : (
            candidateRows.map((row) => (
              <tr key={row.candidateId}>
                <AdminCell column="name">{row.nameEn}</AdminCell>
                <AdminCell column="district">{row.district}</AdminCell>
                <AdminCell column="source">{row.source}</AdminCell>
                <AdminCell column="ops">
                  <TableIconButton
                    iconClassName="bi bi-check-lg"
                    ariaLabel={`Approve ${row.nameEn}`}
                    disabled={mutations.decide.isPending}
                    onClick={() => mutations.decide.mutate({ candidateId: row.candidateId, decision: "approve" })}
                  />
                  <TableIconButton
                    iconClassName="bi bi-x-lg"
                    ariaLabel={`Reject ${row.nameEn}`}
                    disabled={mutations.decide.isPending}
                    onClick={() => mutations.decide.mutate({ candidateId: row.candidateId, decision: "reject" })}
                  />
                </AdminCell>
              </tr>
            ))
          )}
        </AdminDataTable>
        {candidates.hasNextPage ? (
          <button
            type="button"
            className="btn btn-outline-secondary btn-sm mt-2"
            disabled={candidates.isFetchingNextPage}
            onClick={() => void candidates.fetchNextPage()}
          >
            {candidates.isFetchingNextPage ? "Loading…" : `Load more (${candidates.total} total)`}
          </button>
        ) : candidates.total > candidateRows.length ? (
          <p className="small text-muted mb-0 mt-2">{candidates.total} matching candidates.</p>
        ) : null}
      </div>
    </section>
  );
}
