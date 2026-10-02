import type { ReactNode } from "react";
import type { ConvertedNetHkd } from "../hooks/useConvertedNetHkd";
import { GLOBAL_DEFAULT_CURRENCY } from "../lib/currencies";
import { MoneyAmount } from "./ui";

export function ConvertedNetHkdValue({
  converted,
  signed = false,
}: {
  readonly converted: ConvertedNetHkd;
  readonly signed?: boolean;
}): ReactNode {
  if (converted.status === "empty") {
    return <span className="text-muted">—</span>;
  }
  if (converted.status === "loading") {
    return <span className="text-muted">Loading rates…</span>;
  }
  if (converted.status === "error") {
    return <span className="text-danger">Could not load exchange rates.</span>;
  }
  if (converted.status === "fx-missing") {
    return <span className="text-danger">Missing FX rate for a currency.</span>;
  }
  const className = signed
    ? converted.net >= 0
      ? "text-success"
      : "text-danger"
    : undefined;
  return (
    <span className={className}>
      <MoneyAmount amount={converted.net} currency={GLOBAL_DEFAULT_CURRENCY} />
    </span>
  );
}
