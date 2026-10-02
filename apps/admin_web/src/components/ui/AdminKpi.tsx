import type { ReactNode } from "react";
import { listNonZeroMoneyLines } from "../../lib/formatDisplay";
import { MoneyAmount } from "./MoneyAmount";

export type AdminKpiProps = {
  readonly label: string;
  readonly value: ReactNode;
  readonly hint?: string;
};

/** Stacked currency lines inside an `AdminKpi` value. */
export function AdminKpiAmounts({
  amounts,
}: {
  readonly amounts: Readonly<Record<string, number>>;
}) {
  const lines = listNonZeroMoneyLines(amounts);
  if (lines.length === 0) {
    return <span className="admin-kpi-amount">—</span>;
  }
  return (
    <span className="admin-kpi-amounts">
      {lines.map((line) => (
        <MoneyAmount
          key={line.currency}
          amount={line.amount}
          currency={line.currency}
          className="admin-kpi-amount"
        />
      ))}
    </span>
  );
}

export function AdminKpi({ label, value, hint }: AdminKpiProps) {
  return (
    <div className="admin-kpi">
      <div className="admin-kpi-label">{label}</div>
      <div className="admin-kpi-value">{value}</div>
      {hint ? <div className="admin-kpi-hint">{hint}</div> : null}
    </div>
  );
}
