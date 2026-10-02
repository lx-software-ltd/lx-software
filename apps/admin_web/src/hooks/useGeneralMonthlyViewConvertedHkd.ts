import { useMemo } from "react";
import { useFrankfurterRatesToBase } from "./useFrankfurterRatesToBase";
import { useFinance } from "./useFinance";
import { GLOBAL_DEFAULT_CURRENCY } from "../lib/currencies";
import { quoteCurrenciesFromBuckets, sumAmountsToBase } from "../lib/frankfurterRates";
import { LEDGER_RELATED_HOUSE_OPTIONS } from "../lib/houses";
import {
  sumMonthlyFinanceLedgerAmountsGeneral,
  sumMonthlyGeneralExpenseAmountsByCategory,
  EXPENSE_CATEGORIES,
} from "../lib/financeModel";

/**
 * Monthly View card totals: general (non-property) ledger buckets converted to
 * {@link GLOBAL_DEFAULT_CURRENCY}, matching {@link MonthlyViewExpenseAllocationsSection}.
 */
export function useGeneralMonthlyViewConvertedHkd() {
  const { data } = useFinance();
  const generalBuckets = useMemo(
    () =>
      sumMonthlyFinanceLedgerAmountsGeneral(
        data.incomeRecords,
        data.expenseRecords,
        data.expenseIncomeAllocationPercents,
        LEDGER_RELATED_HOUSE_OPTIONS,
        data.allocationRecords,
      ),
    [
      data.allocationRecords,
      data.expenseIncomeAllocationPercents,
      data.expenseRecords,
      data.incomeRecords,
    ],
  );

  const hasActivity = useMemo(() => {
    for (const v of Object.values(generalBuckets.incomeByCurrency)) {
      if (v !== 0) return true;
    }
    for (const v of Object.values(generalBuckets.expensesByCurrency)) {
      if (v !== 0) return true;
    }
    return false;
  }, [generalBuckets]);

  const quoteCurrencies = useMemo(
    () =>
      quoteCurrenciesFromBuckets(
        generalBuckets.incomeByCurrency,
        generalBuckets.expensesByCurrency,
      ),
    [generalBuckets],
  );

  const needsFx = useMemo(
    () =>
      quoteCurrencies.some(
        (c) => c.trim().toUpperCase() !== GLOBAL_DEFAULT_CURRENCY,
      ),
    [quoteCurrencies],
  );

  const ratesQuery = useFrankfurterRatesToBase(GLOBAL_DEFAULT_CURRENCY, quoteCurrencies);

  const convertedHkd = useMemo(() => {
    if (!hasActivity) {
      return { status: "empty" as const };
    }
    let rateByQuote: ReadonlyMap<string, number> = new Map();
    if (needsFx) {
      if (ratesQuery.isPending) {
        return { status: "loading" as const };
      }
      if (ratesQuery.isError) {
        return { status: "error" as const };
      }
      if (!ratesQuery.isSuccess || !ratesQuery.data) {
        return { status: "loading" as const };
      }
      rateByQuote = ratesQuery.data.rateByQuote;
    }
    try {
      const sumBucket = (rec: Readonly<Record<string, number>>): number =>
        sumAmountsToBase(rec, GLOBAL_DEFAULT_CURRENCY, rateByQuote);
      const income = sumBucket(generalBuckets.incomeByCurrency);
      const expenses = sumBucket(generalBuckets.expensesByCurrency);
      const expenseByCategory = sumMonthlyGeneralExpenseAmountsByCategory(
        data.incomeRecords,
        data.expenseRecords,
        data.expenseIncomeAllocationPercents,
        LEDGER_RELATED_HOUSE_OPTIONS,
      );
      const categoryPercentsSorted = EXPENSE_CATEGORIES.map((category) => {
        const buckets: Readonly<Record<string, number>> = expenseByCategory[category] ?? {};
        const amountHkd = sumBucket(buckets);
        const percent = income > 0 ? (amountHkd / income) * 100 : 0;
        return { category, amountHkd, percent };
      }).sort((a, b) => {
        if (b.percent !== a.percent) {
          return b.percent - a.percent;
        }
        return a.category.localeCompare(b.category, undefined, { sensitivity: "base" });
      });
      return {
        status: "ok" as const,
        income,
        expenses,
        net: income - expenses,
        categoryPercentsSorted,
      };
    } catch {
      return { status: "fx-missing" as const };
    }
  }, [
    data.expenseIncomeAllocationPercents,
    data.expenseRecords,
    data.incomeRecords,
    generalBuckets.expensesByCurrency,
    generalBuckets.incomeByCurrency,
    hasActivity,
    needsFx,
    ratesQuery.data,
    ratesQuery.isError,
    ratesQuery.isPending,
    ratesQuery.isSuccess,
  ]);

  return { convertedHkd, hasActivity, needsFx, ratesQuery };
}
