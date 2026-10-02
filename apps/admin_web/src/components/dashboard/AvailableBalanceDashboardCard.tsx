import { type ReactNode, useMemo } from "react";
import { FrankfurterRatesFooterNote, MoneyAmount } from "../ui";
import { useAllocationCoverageDashboardSheet } from "../../hooks/useAllocationCoverageDashboardSheet";
import { useGeneralMonthlyViewConvertedHkd } from "../../hooks/useGeneralMonthlyViewConvertedHkd";
import { useFinance } from "../../hooks/useFinance";
import { GLOBAL_DEFAULT_CURRENCY } from "../../lib/currencies";
import { convertAmountToBase } from "../../lib/frankfurterRates";

type MonthlyNetResult =
  | { readonly ok: true; readonly net: number }
  | { readonly ok: false; readonly node: ReactNode };

function monthlyNetForFormulas(converted: ReturnType<typeof useGeneralMonthlyViewConvertedHkd>["convertedHkd"]): MonthlyNetResult {
  if (converted.status === "empty") {
    return { ok: true, net: 0 };
  }
  if (converted.status === "loading") {
    return { ok: false, node: <span className="text-muted">Loading rates…</span> };
  }
  if (converted.status === "error") {
    return { ok: false, node: <span className="text-danger">Could not load exchange rates.</span> };
  }
  if (converted.status === "fx-missing") {
    return {
      ok: false,
      node: <span className="text-danger">Missing FX rate for a currency.</span>,
    };
  }
  return { ok: true, net: converted.net };
}

function signedMoney(amount: number, currency: string): ReactNode {
  return <MoneyAmount amount={amount} currency={currency} />;
}

export function AvailableBalanceDashboardCard() {
  const { data } = useFinance();
  const base = GLOBAL_DEFAULT_CURRENCY;
  const {
    sheet: allocationSheet,
    needsFx: allocNeedsFx,
    fxError: allocFxError,
    fxLoading: allocFxLoading,
    ratesQuery: allocRatesQuery,
  } = useAllocationCoverageDashboardSheet();
  const { convertedHkd, needsFx: monthlyNeedsFx, ratesQuery: monthlyRatesQuery } =
    useGeneralMonthlyViewConvertedHkd();

  const creditCardRows = useMemo(
    () => data.accountRecords.filter((a) => a.accountType === "Credit Card"),
    [data.accountRecords],
  );

  const creditSumsHkd = useMemo(() => {
    if (allocationSheet.status !== "ok") {
      return null;
    }
    const map = allocationSheet.rateByQuote;
    try {
      let lastStatementSum = 0;
      let currentBalanceSum = 0;
      for (const a of creditCardRows) {
        const lsa = a.lastStatementAmount ?? 0;
        lastStatementSum += convertAmountToBase(lsa, a.currency, base, map);
        currentBalanceSum += convertAmountToBase(a.recordedValue, a.currency, base, map);
      }
      return { lastStatementSum, currentBalanceSum };
    } catch {
      return undefined;
    }
  }, [allocationSheet, creditCardRows, base]);

  const monthlyNetRes = monthlyNetForFormulas(convertedHkd);

  const derivedAmounts = useMemo(() => {
    if (allocationSheet.status !== "ok") {
      return null;
    }
    if (!monthlyNetRes.ok) {
      return null;
    }
    if (creditSumsHkd == null) {
      return { kind: "fx-missing" as const };
    }
    const currentMonth = allocationSheet.diff;
    const N = monthlyNetRes.net;
    const L = creditSumsHkd.lastStatementSum;
    const C = creditSumsHkd.currentBalanceSum;
    const nextMonth = currentMonth + N - L;
    const nextMonthPlus1 = nextMonth + N + L - C;
    return {
      kind: "ok" as const,
      nextMonth,
      nextMonthPlus1,
    };
  }, [allocationSheet, monthlyNetRes, creditSumsHkd]);

  function allocationStatusMessage(): ReactNode {
    if (allocationSheet.status === "empty") {
      return <span className="text-muted">No allocation or coverage data yet.</span>;
    }
    if (allocationSheet.status === "loading") {
      return allocationSheet.stage === "quotes" ? (
        <span className="text-muted">Loading investment quotes…</span>
      ) : (
        <span className="text-muted">Loading exchange rates…</span>
      );
    }
    if (allocationSheet.status === "error") {
      return allocationSheet.stage === "quotes" ? (
        <span className="text-danger">Could not load investment quotes.</span>
      ) : (
        <span className="text-danger">Could not load exchange rates.</span>
      );
    }
    if (allocationSheet.status === "fx-missing") {
      return <span className="text-danger">Missing FX rate for a currency.</span>;
    }
    return null;
  }

  function currentMonthCell(): ReactNode {
    if (allocationSheet.status !== "ok") {
      return allocationStatusMessage();
    }
    return signedMoney(allocationSheet.diff, base);
  }

  function derivedCell(amount: number | undefined): ReactNode {
    if (allocationSheet.status !== "ok") {
      return allocationStatusMessage();
    }
    if (!monthlyNetRes.ok) {
      return monthlyNetRes.node;
    }
    if (derivedAmounts?.kind === "fx-missing") {
      return <span className="text-danger">Missing FX rate for a currency.</span>;
    }
    if (derivedAmounts?.kind !== "ok" || amount === undefined) {
      return <span className="text-muted">—</span>;
    }
    return signedMoney(amount, base);
  }

  return (
    <div className="card h-100 shadow-sm">
      <div className="card-body d-flex flex-column">
        <h2 className="h6 mb-3">
          <strong>Available Balance</strong>
        </h2>
        <p className="text-muted small mb-3">
          Current month matches allocation coverage net. Next month adds the Monthly View net and
          subtracts the sum of last statement amounts on all credit card accounts. The following
          month adds Monthly View net again, adds those statement amounts back, and subtracts credit
          card current balances—all in {base}.
        </p>
        <dl className="row small mb-2">
          <dt className="col-sm-5 text-muted">Current Month</dt>
          <dd className="col-sm-7 text-end mb-0">{currentMonthCell()}</dd>
          <dt className="col-sm-5 text-muted pt-2">Next Month</dt>
          <dd className="col-sm-7 text-end pt-2 mb-0">
            {derivedCell(derivedAmounts?.kind === "ok" ? derivedAmounts.nextMonth : undefined)}
          </dd>
          <dt className="col-sm-5 text-muted pt-2">Next Month +1</dt>
          <dd className="col-sm-7 text-end pt-2 mb-0">
            {derivedCell(
              derivedAmounts?.kind === "ok" ? derivedAmounts.nextMonthPlus1 : undefined,
            )}
          </dd>
        </dl>
        {allocNeedsFx ? (
          <p className="small text-muted mb-1">
            <FrankfurterRatesFooterNote
              needsFx={allocNeedsFx}
              fxError={allocFxError}
              fxLoading={allocFxLoading}
              ratesQuery={allocRatesQuery}
            />
          </p>
        ) : null}
        {monthlyNeedsFx ? (
          <p className="small text-muted mb-0">
            Monthly view rates:{" "}
            <FrankfurterRatesFooterNote
              needsFx={monthlyNeedsFx}
              fxError={monthlyRatesQuery.isError}
              fxLoading={monthlyRatesQuery.isPending}
              ratesQuery={monthlyRatesQuery}
            />
          </p>
        ) : null}
      </div>
    </div>
  );
}
