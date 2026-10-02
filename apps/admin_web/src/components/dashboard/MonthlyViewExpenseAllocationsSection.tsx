import { type ReactNode } from "react";
import { MoneyAmount } from "../ui";
import { useGeneralMonthlyViewConvertedHkd } from "../../hooks/useGeneralMonthlyViewConvertedHkd";
import { GLOBAL_DEFAULT_CURRENCY } from "../../lib/currencies";

function formatExpensePercentOfIncome(percent: number): string {
  const rounded = Math.round(percent * 10) / 10;
  if (Number.isInteger(rounded)) {
    return `${rounded}%`;
  }
  return `${rounded.toFixed(1)}%`;
}

/** Matches {@link AllocationCoverageDashboardCard} allocation rows table styling. */
function expenseAllocationPercentTable(body: ReactNode) {
  return (
    <div className="table-responsive mb-0" style={{ maxHeight: "24rem" }}>
      <table className="table table-sm table-striped mb-0">
        <thead>
          <tr>
            <th className="small">Category</th>
            <th className="small text-end">% of income</th>
          </tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  );
}

export function MonthlyViewExpenseAllocationsSection() {
  const { convertedHkd } = useGeneralMonthlyViewConvertedHkd();

  function generalHkdValue(
    c: typeof convertedHkd,
    kind: "income" | "expenses" | "net" | "netDaily",
  ): ReactNode {
    if (c.status === "empty") {
      return <span className="text-muted">—</span>;
    }
    if (c.status === "loading") {
      return <span className="text-muted">Loading rates…</span>;
    }
    if (c.status === "error") {
      return <span className="text-danger">Could not load exchange rates.</span>;
    }
    if (c.status === "fx-missing") {
      return <span className="text-danger">Missing FX rate for a currency.</span>;
    }
    const amt =
      kind === "income"
        ? c.income
        : kind === "expenses"
          ? c.expenses
          : kind === "net"
            ? c.net
            : c.net / 30;
    return <MoneyAmount amount={amt} currency={GLOBAL_DEFAULT_CURRENCY} />;
  }

  function generalCategoryPercentPanel(c: typeof convertedHkd): ReactNode {
    if (c.status === "empty") {
      return <p className="text-muted small mb-0">No monthly view data yet.</p>;
    }
    if (c.status === "loading") {
      return expenseAllocationPercentTable(
        <tr>
          <td colSpan={2} className="small text-muted">
            Loading rates…
          </td>
        </tr>,
      );
    }
    if (c.status === "error") {
      return expenseAllocationPercentTable(
        <tr>
          <td colSpan={2} className="small text-danger">
            Could not load exchange rates.
          </td>
        </tr>,
      );
    }
    if (c.status === "fx-missing") {
      return expenseAllocationPercentTable(
        <tr>
          <td colSpan={2} className="small text-danger">
            Missing FX rate for a currency.
          </td>
        </tr>,
      );
    }
    if (c.income <= 0) {
      return expenseAllocationPercentTable(
        <tr>
          <td colSpan={2} className="small text-muted">
            Income is zero in {GLOBAL_DEFAULT_CURRENCY}, so category allocations are not shown.
          </td>
        </tr>,
      );
    }
    return expenseAllocationPercentTable(
      c.categoryPercentsSorted.length === 0 ? (
        <tr>
          <td colSpan={2} className="small text-muted">
            No expense categories in this view.
          </td>
        </tr>
      ) : (
        c.categoryPercentsSorted.map(({ category, percent }) => (
          <tr key={category}>
            <td className="small">{category}</td>
            <td className="small text-end text-nowrap">
              {formatExpensePercentOfIncome(percent)}
            </td>
          </tr>
        ))
      ),
    );
  }

  return (
    <div className="row g-3 mb-4">
      <div className="col-12 col-lg-6">
        <div className="card h-100 shadow-sm">
          <div className="card-body d-flex flex-column">
            <h2 className="h6 mb-3">
              <strong>Monthly View</strong>
            </h2>
            <p className="text-muted small mb-3">
              Monthly income and expenses not linked to any property (including derived tax,
              saving, and investment amounts from tagged income with no related property),
              summed in {GLOBAL_DEFAULT_CURRENCY}.
            </p>
            <dl className="row small mb-0">
              <dt className="col-sm-4 text-muted">Income</dt>
              <dd className="col-sm-8">{generalHkdValue(convertedHkd, "income")}</dd>
              <dt className="col-sm-4 text-muted pt-2">Expenses</dt>
              <dd className="col-sm-8 pt-2">{generalHkdValue(convertedHkd, "expenses")}</dd>
              <dt className="col-sm-4 text-muted pt-2">Net</dt>
              <dd className="col-sm-8 pt-2">{generalHkdValue(convertedHkd, "net")}</dd>
              <dt className="col-sm-4 text-muted pt-2">Net (daily)</dt>
              <dd className="col-sm-8 pt-2">{generalHkdValue(convertedHkd, "netDaily")}</dd>
            </dl>
          </div>
        </div>
      </div>
      <div className="col-12 col-lg-6">
        <div className="card h-100 shadow-sm">
          <div className="card-body d-flex flex-column">
            <h2 className="h6 mb-3">
              <strong>Expense Allocations</strong>
            </h2>
            <p className="small text-muted mb-2">
              Expense categories as a share of general income in this monthly view (highest
              first).
            </p>
            {generalCategoryPercentPanel(convertedHkd)}
          </div>
        </div>
      </div>
    </div>
  );
}
