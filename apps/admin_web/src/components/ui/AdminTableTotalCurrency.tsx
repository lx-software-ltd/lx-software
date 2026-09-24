import type { ReactNode } from "react";
import type { CurrencyCode } from "../../lib/currencies";
import { CurrencySelect } from "./CurrencySelect";
import {
  FrankfurterRatesFooterNote,
  type FrankfurterRatesFooterNoteProps,
} from "./FrankfurterRatesFooterNote";

export type AdminTableTotalLabelProps = FrankfurterRatesFooterNoteProps & {
  readonly label?: string;
  /**
   * Amount (and the display-currency picker) shown under the label on phones,
   * where the metric column is hidden so the table is one column.
   */
  readonly phoneValue?: ReactNode;
};

/**
 * "Total" label for a finance table footer with the FX source note underneath.
 * Rendered once, at every breakpoint, so the note never depends on a hidden column.
 */
export function AdminTableTotalLabel({
  label = "Total",
  phoneValue,
  ...note
}: AdminTableTotalLabelProps) {
  return (
    <>
      {label}
      {phoneValue ? <span className="d-md-none d-block mt-1">{phoneValue}</span> : null}
      <span className="d-block small text-muted fw-normal admin-table-total-note">
        <FrankfurterRatesFooterNote {...note} />
      </span>
    </>
  );
}

export type AdminTableTotalCurrencyProps = {
  readonly id: string;
  readonly value: CurrencyCode;
  readonly onChange: (code: CurrencyCode) => void;
  readonly disabled?: boolean;
};

/** Display-currency picker for a table total, labelled for screen readers and rendered once. */
export function AdminTableTotalCurrency({ id, value, onChange, disabled }: AdminTableTotalCurrencyProps) {
  return (
    <CurrencySelect
      id={id}
      className="form-select form-select-sm w-auto d-inline-block mt-1 admin-table-total-ccy"
      ariaLabel="Total display currency"
      value={value}
      onChange={onChange}
      disabled={disabled}
    />
  );
}
