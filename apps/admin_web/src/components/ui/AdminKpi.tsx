import type { ReactNode } from "react";

export type AdminKpiProps = {
  readonly label: string;
  readonly value: ReactNode;
  readonly hint?: string;
};

export function AdminKpi({ label, value, hint }: AdminKpiProps) {
  return (
    <div className="admin-kpi">
      <div className="admin-kpi-label">{label}</div>
      <div className="admin-kpi-value">{value}</div>
      {hint ? <div className="admin-kpi-hint">{hint}</div> : null}
    </div>
  );
}

/** Twelve-or-fewer point line. Values are plotted in order, scaled to the series. */
export function AdminSparkline({ values }: { readonly values: readonly number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 72;
  const height = 28;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * (height - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg className="admin-sparkline" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline points={points} fill="none" />
    </svg>
  );
}
