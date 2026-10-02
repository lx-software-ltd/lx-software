import { useMemo } from "react";
import { ConvertedNetHkdValue } from "./ConvertedNetHkdValue";
import { useConvertedNetHkd } from "../hooks/useConvertedNetHkd";
import {
  FISCAL_YEAR_OPTIONS,
  formatFiscalYearIdLabel,
  fiscalYearIdToStartCalendarYear,
  sumHouseStatementLinesForFiscalYear,
  type FiscalYearId,
} from "../lib/fiscalYearFinance";
import type { HouseFinanceData } from "../lib/financeModel";
import { FrankfurterRatesFooterNote, MoneyAmount } from "./ui";

function sortedCurrencyEntries(
  record: Readonly<Record<string, number>>,
): [string, number][] {
  return Object.entries(record)
    .filter(([, amount]) => amount !== 0)
    .sort(([a], [b]) => a.localeCompare(b));
}

function CurrencyBucketList({
  buckets,
  emptyLabel,
}: {
  readonly buckets: Readonly<Record<string, number>>;
  readonly emptyLabel: string;
}) {
  const entries = sortedCurrencyEntries(buckets);
  if (entries.length === 0) {
    return <span className="text-muted">{emptyLabel}</span>;
  }
  return (
    <ul className="list-unstyled mb-0 small">
      {entries.map(([currency, amount]) => (
        <li key={currency}>
          <MoneyAmount amount={amount} currency={currency} />
        </li>
      ))}
    </ul>
  );
}

export function StatementBookDashboardCard({
  title,
  showTitle = true,
  data,
  fiscalYear,
  onFiscalYearChange,
}: {
  readonly title: string;
  readonly showTitle?: boolean;
  readonly data: HouseFinanceData;
  readonly fiscalYear: FiscalYearId;
  readonly onFiscalYearChange: (id: FiscalYearId) => void;
}) {
  const sums = useMemo(
    () =>
      sumHouseStatementLinesForFiscalYear(
        data.lines,
        fiscalYearIdToStartCalendarYear(fiscalYear),
      ),
    [data.lines, fiscalYear],
  );
  const { converted, needsFx, ratesQuery, fxLoading, fxError } = useConvertedNetHkd(
    sums.incomeByCurrency,
    sums.expensesByCurrency,
  );
  const fyLabel = formatFiscalYearIdLabel(fiscalYear);

  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        {showTitle ? (
          <h2 className="h6 mb-3">
            <strong>{title}</strong>
          </h2>
        ) : null}
        <div className="mb-3">
          <select
            className="form-select form-select-sm"
            value={fiscalYear}
            onChange={(e) => onFiscalYearChange(e.target.value as FiscalYearId)}
            aria-label={`${title}: ${fyLabel}`}
          >
            {FISCAL_YEAR_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <dl className="row small mb-0">
          <dt className="col-sm-4 text-muted">Gains</dt>
          <dd className="col-sm-8">
            <CurrencyBucketList buckets={sums.incomeByCurrency} emptyLabel="—" />
          </dd>
          <dt className="col-sm-4 text-muted pt-2">Expenses</dt>
          <dd className="col-sm-8 pt-2">
            <CurrencyBucketList buckets={sums.expensesByCurrency} emptyLabel="—" />
          </dd>
          <dt className="col-sm-4 text-muted pt-2">Net</dt>
          <dd className="col-sm-8 pt-2">
            <ConvertedNetHkdValue converted={converted} />
          </dd>
        </dl>
        <p className="text-muted small mb-0 mt-3">
          {showTitle
            ? `Totals use net amounts from ${title} lines in this fiscal year.`
            : "Totals use net amounts in this fiscal year."}{" "}
          Gains and expenses stay in the line currency. Net is one HKD total.
          {needsFx ? (
            <>
              {" "}
              <FrankfurterRatesFooterNote
                needsFx={needsFx}
                fxError={fxError}
                fxLoading={fxLoading}
                ratesQuery={ratesQuery}
              />
            </>
          ) : null}
        </p>
      </div>
    </div>
  );
}
