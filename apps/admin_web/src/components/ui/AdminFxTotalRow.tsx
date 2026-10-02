import type { ReactNode } from "react";
import type { CurrencyCode } from "../../lib/currencies";
import type { FrankfurterRatesFooterNoteProps } from "./FrankfurterRatesFooterNote";
import { AdminCell } from "./AdminDataTable";
import { AdminTableTotalCurrency, AdminTableTotalLabel } from "./AdminTableTotalCurrency";
import { MoneyAmount } from "./MoneyAmount";

export type AdminFxTotalCell =
  | { readonly kind: "label" }
  | { readonly kind: "empty"; readonly column: string }
  | {
      readonly kind: "amount";
      readonly column: string;
      readonly total: number | null;
      readonly picker?: boolean;
      /** Overrides the row-level desktop picker id when several amount cells have a picker. */
      readonly pickerId?: string;
      readonly pickerAriaLabel?: string;
    };

export type AdminFxTotalRowProps = FrankfurterRatesFooterNoteProps & {
  readonly labelColumn: string;
  readonly label?: string;
  /** Replaces the standard total label when the footer note is not Frankfurter. */
  readonly labelContent?: ReactNode;
  readonly sheetId: string;
  readonly currency: CurrencyCode;
  readonly onCurrencyChange: (code: CurrencyCode) => void;
  readonly cells: readonly AdminFxTotalCell[];
  /** Phone picker id. Defaults to `${sheetId}-total-ccy-phone`. */
  readonly phonePickerId?: string;
  /** Desktop picker id. Defaults to `${sheetId}-total-ccy`. */
  readonly pickerId?: string;
  /** Amount shown beside the label on phones. Defaults to the picker column. */
  readonly phoneTotal?: number | null;
};

function amountNode(total: number | null, currency: CurrencyCode): ReactNode {
  if (total === null) return <span className="text-muted">—</span>;
  return <MoneyAmount amount={total} currency={currency} />;
}

export function AdminFxTotalRow({
  labelColumn,
  label = "Total",
  labelContent,
  sheetId,
  currency,
  onCurrencyChange,
  cells,
  phonePickerId = `${sheetId}-total-ccy-phone`,
  pickerId = `${sheetId}-total-ccy`,
  phoneTotal,
  ...note
}: AdminFxTotalRowProps) {
  const pickerCell = cells.find((cell) => cell.kind === "amount" && cell.picker);
  const phoneAmount =
    phoneTotal !== undefined ? phoneTotal : pickerCell && pickerCell.kind === "amount" ? pickerCell.total : null;
  const phoneValue = (
    <>
      {amountNode(phoneAmount, currency)}
      <br />
      <AdminTableTotalCurrency
        id={phonePickerId}
        value={currency}
        onChange={onCurrencyChange}
        disabled={note.fxLoading}
      />
    </>
  );

  return (
    <tr className="table-group-divider table-secondary fw-semibold">
      {cells.map((cell) => {
        if (cell.kind === "label") {
          return (
            <AdminCell key={labelColumn} column={labelColumn} className="small">
              {labelContent ?? (
                <AdminTableTotalLabel label={label} {...note} phoneValue={phoneValue} />
              )}
            </AdminCell>
          );
        }
        if (cell.kind === "empty") {
          return <AdminCell key={cell.column} column={cell.column} className="small" />;
        }
        return (
          <AdminCell key={cell.column} column={cell.column} className="small text-end">
            {amountNode(cell.total, currency)}
            {cell.picker ? (
              <>
                <br />
                <AdminTableTotalCurrency
                  id={cell.pickerId ?? pickerId}
                  ariaLabel={cell.pickerAriaLabel}
                  value={currency}
                  onChange={onCurrencyChange}
                  disabled={note.fxLoading}
                />
              </>
            ) : null}
          </AdminCell>
        );
      })}
    </tr>
  );
}
