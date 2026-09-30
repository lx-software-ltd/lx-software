import { AdminKpi, AdminKpiAmounts } from "./ui";
import { useMirroredBookSummary } from "../hooks/useMirroredBookSummary";
import { getAdminApiErrorMessage } from "../lib/apiAdminClient";
import { formatDateTimeHKT, formatNonZeroMoneyLines } from "../lib/formatDisplay";
import type { StatementBookKey } from "../lib/financeTypes";
import { STATEMENT_BOOK_DISPLAY_LABEL } from "../lib/statementOwners";

/** Outstanding invoices and the last cash mirror. Lines stay on the book tabs. */
export function MirroredBookSummaryCard({
  bookKey,
}: {
  readonly bookKey: StatementBookKey;
}) {
  const title = STATEMENT_BOOK_DISPLAY_LABEL[bookKey];
  const { query, sync } = useMirroredBookSummary(bookKey);
  const summary = query.data;
  const syncError = getAdminApiErrorMessage(sync.error);

  return (
    <div className="card shadow-sm">
      <div className="card-body">
        <div className="d-flex justify-content-end mb-3">
          <button
            type="button"
            className="btn btn-sm btn-outline-primary"
            disabled={sync.isPending || query.isLoading}
            onClick={() => void sync.mutate()}
          >
            {sync.isPending ? "Syncing…" : "Sync now"}
          </button>
        </div>
        {query.isLoading ? (
          <p className="small text-muted mb-0">Loading the product database summary…</p>
        ) : null}
        {query.isError ? (
          <div className="alert alert-danger py-2 small mb-0" role="alert">
            Could not load the {title} summary.
          </div>
        ) : null}
        {summary ? (
          <>
            <div className="admin-kpi-row">
              <AdminKpi
                label="Outstanding"
                value={<AdminKpiAmounts lines={formatNonZeroMoneyLines(summary.outstandingByCurrency)} />}
                hint="Issued, unpaid"
              />
              <AdminKpi label="Open invoices" value={summary.openInvoices} hint="Count" />
              <AdminKpi label="Submitted" value={summary.submittedExpenses} hint="Expenses" />
              <AdminKpi label="Paid" value={summary.paidExpenses} hint="Expenses" />
              <AdminKpi
                label="Last synced"
                value={summary.syncedAt ? formatDateTimeHKT(summary.syncedAt) : "—"}
              />
            </div>
            {summary.configured ? null : (
              <p className="small text-muted mb-0 mt-3">
                The {title} database is not connected.
              </p>
            )}
            {summary.skippedUnsupportedCurrency > 0 ? (
              <p className="small text-muted mb-0 mt-3">
                {summary.skippedUnsupportedCurrency} rows used a currency this admin does not keep.
              </p>
            ) : null}
          </>
        ) : null}
        {syncError ? (
          <div className="alert alert-danger py-2 small mb-0 mt-3" role="alert">
            {syncError}
          </div>
        ) : null}
      </div>
    </div>
  );
}
