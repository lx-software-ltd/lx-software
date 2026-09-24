import { useMemo, useState } from "react";
import {
  AdminCell,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  MoneyAmount,
} from "../ui";
import { useBoardReceivables } from "../../hooks/useBoardReceivables";
import type { BoardReceivablesInvoice, BoardReceivablesSubscription } from "../../lib/boardModel";

export type BoardReceivablesViewProps = {
  readonly overdueCount?: number;
  readonly errorText: (err: unknown) => string | null;
};

const INVOICE_COLUMNS = [
  { key: "number", header: "Number" },
  { key: "due", header: "Due", priority: "secondary" as const },
  { key: "amount", header: "Amount", className: "text-end" },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "fps", header: "FPS", priority: "tertiary" as const },
] as const;

const SUB_COLUMNS = [
  { key: "plan", header: "Plan" },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "renews", header: "Renews", priority: "secondary" as const },
  { key: "payer", header: "Payer", priority: "tertiary" as const },
] as const;

const BUCKETS: readonly { readonly id: string; readonly label: string }[] = [
  { id: "current", label: "Current (< 7 days)" },
  { id: "d7", label: "D+7" },
  { id: "d21", label: "D+21" },
  { id: "d35", label: "D+35" },
];

function matchesFilter(parts: readonly unknown[], query: string): boolean {
  if (!query) return true;
  return parts.join(" ").toLowerCase().includes(query);
}

function InvoiceRows({ rows }: { readonly rows: readonly BoardReceivablesInvoice[] }) {
  if (rows.length === 0) {
    return <AdminDataTableEmptyRow colSpan={INVOICE_COLUMNS.length} message="None in this bucket." />;
  }
  return (
    <>
      {rows.map((inv) => (
        <tr key={inv.id}>
          <AdminCell column="number">
            {inv.number}
            <AdminDataTableCellMeta>
              {inv.status}
              {inv.due_on ? ` · due ${inv.due_on}` : ""}
              {" · "}
              <MoneyAmount amount={Number(inv.amount_hkd)} currency="HKD" />
            </AdminDataTableCellMeta>
            {inv.fps_reference ? (
              <AdminDataTableCellMeta until="tertiary">
                FPS <span className="font-monospace">{inv.fps_reference}</span>
              </AdminDataTableCellMeta>
            ) : null}
          </AdminCell>
          <AdminCell column="due">{inv.due_on ?? "—"}</AdminCell>
          <AdminCell column="amount" className="text-end">
            <MoneyAmount amount={Number(inv.amount_hkd)} currency="HKD" />
          </AdminCell>
          <AdminCell column="status">
            <span className="badge text-bg-light border">{inv.status}</span>
          </AdminCell>
          <AdminCell column="fps" className="font-monospace small">{inv.fps_reference ?? "—"}</AdminCell>
        </tr>
      ))}
    </>
  );
}

export function BoardReceivablesView({ overdueCount, errorText }: BoardReceivablesViewProps) {
  const query = useBoardReceivables();
  const data = query.data;
  const [invoiceFilter, setInvoiceFilter] = useState("");
  const [subFilter, setSubFilter] = useState("");
  const invoiceQuery = invoiceFilter.trim().toLowerCase();
  const subQuery = subFilter.trim().toLowerCase();

  const filteredBuckets = useMemo(() => {
    const buckets = data?.aging.buckets ?? {};
    const out: Record<string, BoardReceivablesInvoice[]> = {};
    for (const [key, rows] of Object.entries(buckets)) {
      out[key] = (rows ?? []).filter((inv) =>
        matchesFilter([inv.number, inv.status, inv.due_on, inv.fps_reference], invoiceQuery),
      );
    }
    return out;
  }, [data, invoiceQuery]);

  const subscriptions = useMemo(
    () =>
      (data?.subscriptions ?? []).filter((s: BoardReceivablesSubscription) =>
        matchesFilter([s.plan_name, s.status, s.renews_on, s.payer_contact], subQuery),
      ),
    [data, subQuery],
  );
  const pastDue =
    overdueCount ??
    (data?.aging
      ? (data.aging.buckets.d7?.length ?? 0) +
        (data.aging.buckets.d21?.length ?? 0) +
        (data.aging.buckets.d35?.length ?? 0)
      : 0);

  return (
    <div className="card shadow-sm mb-4">
      <div className="card-body">
        <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
          <h2 className="admin-card-title mb-0">Receivables</h2>
          <div className="small text-muted">
            {data?.configured
              ? `${data.aging.outstandingHkd ?? 0} HKD outstanding${pastDue ? ` · ${pastDue} past due` : ""}`
              : "Data API not configured"}
          </div>
        </div>
        <p className="text-muted small">
          Listing subscriptions and invoices live in the siutindei Aurora database (
          <code>scripts/siutindei/receivables.sql</code>). Matched payments and issued invoices are
          mirrored nightly into the Siu Tin Dei statement book. The board never moves money out of
          the account.
        </p>
        {query.isError ? <div className="alert alert-danger py-2 small">{errorText(query.error)}</div> : null}
        {!data?.configured && !query.isLoading ? (
          <div className="alert alert-light border small mb-0">
            Set <code>SiutindeiClusterArn</code> and <code>SiutindeiDbSecretArn</code>, enable the
            RDS Data API on the cluster, and apply the migration in the siutindei repo.
          </div>
        ) : null}
        {data?.configured ? (
          <>
            {BUCKETS.map((b) => (
              <div key={b.id} className="mb-3">
                <h3 className="admin-card-title">{b.label}</h3>
                <AdminDataTable
                  columns={INVOICE_COLUMNS}
                  filterValue={invoiceFilter}
                  onFilterChange={setInvoiceFilter}
                  filterPlaceholder="Filter invoices…"
                >
                  <InvoiceRows rows={filteredBuckets[b.id] ?? []} />
                </AdminDataTable>
              </div>
            ))}
            <h3 className="admin-card-title mt-4">Subscriptions</h3>
            <AdminDataTable
              columns={SUB_COLUMNS}
              filterValue={subFilter}
              onFilterChange={setSubFilter}
              filterPlaceholder="Filter subscriptions…"
            >
              {subscriptions.length === 0 ? (
                <AdminDataTableEmptyRow colSpan={SUB_COLUMNS.length} message="No subscriptions yet. Pricing is a first CFO action." />
              ) : (
                subscriptions.map((s) => (
                  <tr key={s.id}>
                    <AdminCell column="plan">
                      {s.plan_name ?? "—"}{" "}
                      {s.price_hkd != null ? <MoneyAmount amount={Number(s.price_hkd)} currency="HKD" /> : null}
                      <AdminDataTableCellMeta>
                        {s.status}
                        {s.renews_on ? ` · renews ${s.renews_on}` : ""}
                      </AdminDataTableCellMeta>
                      {s.payer_contact ? (
                        <AdminDataTableCellMeta until="tertiary">{s.payer_contact}</AdminDataTableCellMeta>
                      ) : null}
                    </AdminCell>
                    <AdminCell column="status">{s.status}</AdminCell>
                    <AdminCell column="renews">{s.renews_on ?? "—"}</AdminCell>
                    <AdminCell column="payer">{s.payer_contact ?? "—"}</AdminCell>
                  </tr>
                ))
              )}
            </AdminDataTable>
          </>
        ) : null}
      </div>
    </div>
  );
}
