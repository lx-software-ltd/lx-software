import { useMemo } from "react";
import { MoneyAmount } from "../ui";
import { useFinance } from "../../hooks/useFinance";
import {
  FISCAL_YEAR_OPTIONS,
  formatFiscalYearIdLabel,
  type FiscalYearId,
  fiscalYearIdToStartCalendarYear,
  sumHouseStatementLinesForFiscalYear,
} from "../../lib/fiscalYearFinance";
import {
  housePropertyEquityByCurrency,
  monthlyLedgerNetByCurrency,
  sumMonthlyFinanceLedgerAmountsByHouse,
  type HouseKey,
} from "../../lib/financeModel";

function sortedCurrencyEntries(record: Readonly<Record<string, number>>): [string, number][] {
  return Object.entries(record)
    .filter(([, amount]) => amount !== 0)
    .sort(([a], [b]) => a.localeCompare(b));
}

function FiscalBucketList({
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

function MonthlyNetByCurrencyList({
  netByCurrency,
  emptyLabel,
}: {
  readonly netByCurrency: Readonly<Record<string, number>>;
  readonly emptyLabel: string;
}) {
  const currencies = Object.keys(netByCurrency).sort((a, b) => a.localeCompare(b));
  const currency = currencies[0];
  if (!currency) {
    return <span className="text-muted">{emptyLabel}</span>;
  }
  const amount = netByCurrency[currency] ?? 0;
  return (
    <ul className="list-unstyled mb-0 small">
      <li>
        <MoneyAmount amount={amount} currency={currency} />
      </li>
    </ul>
  );
}

function SignedBucketList({
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

export function HouseSummaryCard({
  houseName,
  houseKey,
  fiscalYear,
  onFiscalYearChange,
}: {
  readonly houseName: string;
  readonly houseKey: HouseKey;
  readonly fiscalYear: FiscalYearId;
  readonly onFiscalYearChange: (id: FiscalYearId) => void;
}) {
  const { data } = useFinance();
  const house = data[houseKey];
  const sums = useMemo(
    () =>
      sumHouseStatementLinesForFiscalYear(
        house.lines,
        fiscalYearIdToStartCalendarYear(fiscalYear),
      ),
    [house.lines, fiscalYear],
  );

  const monthlySums = useMemo(
    () =>
      sumMonthlyFinanceLedgerAmountsByHouse(
        data.incomeRecords,
        data.expenseRecords,
        houseKey,
        data.expenseIncomeAllocationPercents,
        data.allocationRecords,
      ),
    [
      data.allocationRecords,
      data.expenseIncomeAllocationPercents,
      data.expenseRecords,
      data.incomeRecords,
      houseKey,
    ],
  );

  const monthlyNetByCurrency = useMemo(
    () => monthlyLedgerNetByCurrency(monthlySums),
    [monthlySums],
  );

  const equity = useMemo(
    () =>
      housePropertyEquityByCurrency(data.investmentRecords, data.liabilityRecords, houseKey),
    [data.investmentRecords, data.liabilityRecords, houseKey],
  );
  const hasEquityData =
    Object.keys(equity.valueByCurrency).length > 0 ||
    Object.keys(equity.liabilitiesByCurrency).length > 0;

  const fyLabel = formatFiscalYearIdLabel(fiscalYear);

  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 mb-3">
          <strong>{houseName}</strong>
        </h2>
        <div className="mb-3">
          <select
            className="form-select form-select-sm"
            value={fiscalYear}
            onChange={(e) => onFiscalYearChange(e.target.value as FiscalYearId)}
            aria-label={`${houseName}: ${fyLabel}`}
          >
            {FISCAL_YEAR_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <dl className="row small mb-0 flex-grow-1">
          <dt className="col-sm-4 text-muted">Income</dt>
          <dd className="col-sm-8">
            <FiscalBucketList buckets={sums.incomeByCurrency} emptyLabel="—" />
          </dd>
          <dt className="col-sm-4 text-muted pt-2">Expenses</dt>
          <dd className="col-sm-8 pt-2">
            <FiscalBucketList buckets={sums.expensesByCurrency} emptyLabel="—" />
          </dd>
          <dt className="col-sm-4 text-muted pt-2">Mortgage</dt>
          <dd className="col-sm-8 pt-2">
            <FiscalBucketList buckets={sums.mortgageByCurrency} emptyLabel="—" />
          </dd>
        </dl>
        <p className="text-muted small mb-0 mt-3">
          Totals use net amounts from house statement lines in this period.
        </p>
        <hr className="my-3" />
        <p className="small text-muted mb-2">Monthly income and expenses</p>
        <dl className="row small mb-0">
          <dt className="col-sm-4 text-muted">Income</dt>
          <dd className="col-sm-8">
            <FiscalBucketList buckets={monthlySums.incomeByCurrency} emptyLabel="—" />
          </dd>
          <dt className="col-sm-4 text-muted pt-2">Expenses</dt>
          <dd className="col-sm-8 pt-2">
            <FiscalBucketList buckets={monthlySums.expensesByCurrency} emptyLabel="—" />
          </dd>
          <dt className="col-sm-4 text-muted pt-2">Net</dt>
          <dd className="col-sm-8 pt-2">
            <MonthlyNetByCurrencyList netByCurrency={monthlyNetByCurrency} emptyLabel="—" />
          </dd>
        </dl>
        {hasEquityData ? (
          <>
            <hr className="my-3" />
            <p className="small text-muted mb-2">Property equity</p>
            <dl className="row small mb-0">
              <dt className="col-sm-4 text-muted">Value</dt>
              <dd className="col-sm-8">
                <FiscalBucketList buckets={equity.valueByCurrency} emptyLabel="—" />
              </dd>
              <dt className="col-sm-4 text-muted pt-2">Liabilities</dt>
              <dd className="col-sm-8 pt-2">
                <FiscalBucketList buckets={equity.liabilitiesByCurrency} emptyLabel="—" />
              </dd>
              <dt className="col-sm-4 text-muted pt-2">Equity</dt>
              <dd className="col-sm-8 pt-2">
                <SignedBucketList buckets={equity.equityByCurrency} emptyLabel="—" />
              </dd>
            </dl>
            <p className="text-muted small mb-0 mt-2">
              Real Estate investment value linked to this property minus linked liability
              balances.
            </p>
          </>
        ) : null}
      </div>
    </div>
  );
}
