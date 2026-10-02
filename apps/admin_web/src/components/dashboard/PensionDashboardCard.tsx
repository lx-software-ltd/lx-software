import { type ReactNode, useMemo, useState } from "react";
import { CurrencySelect, FrankfurterRatesFooterNote, MoneyAmount } from "../ui";
import { useFrankfurterRatesForTotals } from "../../hooks/useFrankfurterRatesForTotals";
import { useFinance } from "../../hooks/useFinance";
import {
  coerceSupportedCurrency,
  GLOBAL_DEFAULT_CURRENCY,
  type CurrencyCode,
} from "../../lib/currencies";
import { convertAmountToBase } from "../../lib/frankfurterRates";
import { ledgerMonthlyAmount } from "../../lib/financeModel";

export function PensionDashboardCard() {
  const { data } = useFinance();
  const [totalDisplayCurrency, setTotalDisplayCurrency] = useState<CurrencyCode>(
    GLOBAL_DEFAULT_CURRENCY,
  );

  const pensionParts = useMemo(() => {
    const parts: { readonly amount: number; readonly currency: string }[] = [];
    for (const r of data.pensionRecords) {
      parts.push({ amount: r.value, currency: r.currency });
    }
    for (const a of data.allocationRecords) {
      if (a.isPension === true) {
        parts.push({ amount: a.accumulatedAmount, currency: a.currency });
      }
    }
    return parts;
  }, [data.allocationRecords, data.pensionRecords]);

  const salaryRecords = useMemo(
    () =>
      data.incomeRecords.filter(
        (r) => r.category === "Salary" && r.isDerivedFromAllocation !== true,
      ),
    [data.incomeRecords],
  );

  const recordCurrencies = useMemo(() => {
    const s = new Set<string>();
    for (const p of pensionParts) {
      s.add(p.currency);
    }
    for (const r of salaryRecords) {
      s.add(r.currency);
    }
    return [...s];
  }, [pensionParts, salaryRecords]);

  const { needsFx, ratesQuery, fxLoading, fxError } = useFrankfurterRatesForTotals(
    totalDisplayCurrency,
    recordCurrencies,
  );

  const convertedPensionTotal = useMemo(() => {
    const fundEmpty = data.pensionRecords.length === 0;
    const allocEmpty = !data.allocationRecords.some((r) => r.isPension === true);
    if (fundEmpty && allocEmpty) {
      return { status: "empty" as const };
    }
    let map: ReadonlyMap<string, number> = new Map();
    if (needsFx) {
      if (fxLoading) {
        return { status: "loading" as const };
      }
      if (fxError || !ratesQuery.isSuccess || !ratesQuery.data) {
        return { status: "error" as const };
      }
      map = ratesQuery.data.rateByQuote;
    }
    try {
      const sum = pensionParts.reduce(
        (acc, p) =>
          acc +
          convertAmountToBase(p.amount, p.currency, totalDisplayCurrency, map),
        0,
      );
      return { status: "ok" as const, sum };
    } catch {
      return { status: "fx-missing" as const };
    }
  }, [
    data.allocationRecords,
    data.pensionRecords,
    fxError,
    fxLoading,
    needsFx,
    pensionParts,
    ratesQuery.data,
    ratesQuery.isSuccess,
    totalDisplayCurrency,
  ]);

  const convertedSalaryAnnual = useMemo(() => {
    if (salaryRecords.length === 0) {
      return { status: "empty" as const };
    }
    let map: ReadonlyMap<string, number> = new Map();
    if (needsFx) {
      if (fxLoading) {
        return { status: "loading" as const };
      }
      if (fxError || !ratesQuery.isSuccess || !ratesQuery.data) {
        return { status: "error" as const };
      }
      map = ratesQuery.data.rateByQuote;
    }
    try {
      const sum = salaryRecords.reduce((acc, r) => {
        const annual = ledgerMonthlyAmount(r) * 12;
        return (
          acc +
          convertAmountToBase(annual, r.currency, totalDisplayCurrency, map)
        );
      }, 0);
      return { status: "ok" as const, sum };
    } catch {
      return { status: "fx-missing" as const };
    }
  }, [
    fxError,
    fxLoading,
    needsFx,
    ratesQuery.data,
    ratesQuery.isSuccess,
    salaryRecords,
    totalDisplayCurrency,
  ]);

  const yearSalaryRatioDisplay = useMemo((): ReactNode => {
    if (convertedPensionTotal.status === "empty") {
      return <span className="text-muted">—</span>;
    }
    if (
      convertedPensionTotal.status === "loading" ||
      convertedSalaryAnnual.status === "loading"
    ) {
      return <span className="text-muted">Loading rates…</span>;
    }
    if (
      convertedPensionTotal.status === "error" ||
      convertedSalaryAnnual.status === "error"
    ) {
      return <span className="text-danger">Could not load exchange rates.</span>;
    }
    if (
      convertedPensionTotal.status === "fx-missing" ||
      convertedSalaryAnnual.status === "fx-missing"
    ) {
      return <span className="text-danger">Missing FX rate for a currency.</span>;
    }
    if (convertedSalaryAnnual.status === "empty" || convertedSalaryAnnual.sum <= 0) {
      return (
        <span className="text-muted">
          — (no annual salary in the Salary category)
        </span>
      );
    }
    const ratio = convertedPensionTotal.sum / convertedSalaryAnnual.sum;
    const rounded = Math.round(ratio * 100) / 100;
    return (
      <span>
        {Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(2)}
        <span className="text-muted">×</span>
        <span className="text-muted small ms-1">
          (pension ÷ annual salary, {totalDisplayCurrency})
        </span>
      </span>
    );
  }, [convertedPensionTotal, convertedSalaryAnnual, totalDisplayCurrency]);

  function pensionTotalBody(): ReactNode {
    if (convertedPensionTotal.status === "empty") {
      return <span className="text-muted">—</span>;
    }
    if (convertedPensionTotal.status === "loading") {
      return <span className="text-muted">Loading rates…</span>;
    }
    if (convertedPensionTotal.status === "error") {
      return <span className="text-danger">Could not load exchange rates.</span>;
    }
    if (convertedPensionTotal.status === "fx-missing") {
      return <span className="text-danger">Missing FX rate for a currency.</span>;
    }
    return (
      <MoneyAmount
        amount={convertedPensionTotal.sum}
        currency={totalDisplayCurrency}
      />
    );
  }

  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 mb-3">
          <strong>Pension</strong>
        </h2>
        <p className="text-muted small mb-3">
          Total pension (fund rows plus allocations tagged Pension), converted to your chosen
          display currency—the same total as on the Finance Pension tab.
        </p>
        <div className="d-flex flex-wrap align-items-center gap-2 mb-2">
          <span className="fw-semibold">{pensionTotalBody()}</span>
          <CurrencySelect
            id="dashboard-pension-total-ccy"
            className="form-select form-select-sm w-auto"
            value={totalDisplayCurrency}
            onChange={(code) =>
              setTotalDisplayCurrency(coerceSupportedCurrency(code, GLOBAL_DEFAULT_CURRENCY))
            }
            disabled={fxLoading}
          />
        </div>
        <p className="small text-muted mb-3">
          <FrankfurterRatesFooterNote
            needsFx={needsFx}
            fxError={fxError}
            fxLoading={fxLoading}
            ratesQuery={ratesQuery}
          />
        </p>
        <dl className="row small mb-0">
          <dt className="col-sm-5 text-muted">Year Salary Ratio</dt>
          <dd className="col-sm-7 mb-0">{yearSalaryRatioDisplay}</dd>
        </dl>
        <p className="text-muted small mb-0 mt-2">
          Annual salary sums Income rows in the Salary category (monthly amounts × 12, yearly
          amounts as entered), in the same display currency.
        </p>
      </div>
    </div>
  );
}
