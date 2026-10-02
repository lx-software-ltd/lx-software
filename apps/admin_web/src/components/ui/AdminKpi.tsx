import type { ReactNode } from "react";

export type AdminKpiProps = {
  readonly label: string;
  readonly value: ReactNode;
  readonly hint?: string;
};

/** Stacked currency lines inside an `AdminKpi` value. */
export function AdminKpiAmounts({ lines }: { readonly lines: readonly string[] }) {
  return (
    <span className="admin-kpi-amounts">
      {lines.map((line, index) => (
        <span key={`${line}-${index}`} className="admin-kpi-amount">
          {line}
        </span>
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
