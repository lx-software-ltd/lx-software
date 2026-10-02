import { useMemo } from "react";
import { GLOBAL_DEFAULT_CURRENCY } from "../lib/currencies";
import {
  netGainsMinusExpensesInBase,
  quoteCurrenciesFromBuckets,
} from "../lib/frankfurterRates";
import { useFrankfurterRatesForTotals } from "./useFrankfurterRatesForTotals";

export type ConvertedNetHkd =
  | { readonly status: "empty" }
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | { readonly status: "fx-missing" }
  | { readonly status: "ok"; readonly net: number };

/**
 * Converts statement-book gains and expenses to {@link GLOBAL_DEFAULT_CURRENCY}
 * via Frankfurter, then returns one net (gains − expenses).
 */
export function useConvertedNetHkd(
  gains: Readonly<Record<string, number>>,
  expenses: Readonly<Record<string, number>>,
) {
  const quoteCurrencies = useMemo(
    () => quoteCurrenciesFromBuckets(gains, expenses),
    [gains, expenses],
  );
  const { needsFx, ratesQuery, fxLoading, fxError } = useFrankfurterRatesForTotals(
    GLOBAL_DEFAULT_CURRENCY,
    quoteCurrencies,
  );

  const converted = useMemo((): ConvertedNetHkd => {
    if (quoteCurrencies.length === 0) {
      return { status: "empty" };
    }
    let rateByQuote: ReadonlyMap<string, number> = new Map();
    if (needsFx) {
      if (fxLoading) {
        return { status: "loading" };
      }
      if (fxError || !ratesQuery.isSuccess || !ratesQuery.data) {
        return { status: "error" };
      }
      rateByQuote = ratesQuery.data.rateByQuote;
    }
    try {
      return {
        status: "ok",
        net: netGainsMinusExpensesInBase(
          gains,
          expenses,
          GLOBAL_DEFAULT_CURRENCY,
          rateByQuote,
        ),
      };
    } catch {
      return { status: "fx-missing" };
    }
  }, [
    expenses,
    fxError,
    fxLoading,
    gains,
    needsFx,
    quoteCurrencies.length,
    ratesQuery.data,
    ratesQuery.isSuccess,
  ]);

  return { converted, needsFx, ratesQuery, fxLoading, fxError };
}
