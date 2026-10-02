import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import type { CurrencyCode } from "../lib/currencies";
import { fetchFrankfurterRatesToBase } from "../lib/frankfurterRates";
import { keys } from "../lib/queryKeys";

/**
 * Latest FX rows where `1 baseCurrency` equals `rate` units of each quote.
 * Disabled when every quote equals the base (no network).
 */
export function useFrankfurterRatesToBase(
  baseCurrency: CurrencyCode,
  quoteCurrencies: readonly string[],
) {
  const sortedUniqueQuotes = useMemo(() => {
    const base = baseCurrency.trim().toUpperCase();
    const s = new Set(
      quoteCurrencies.map((c) => c.trim().toUpperCase()).filter((c) => c !== base),
    );
    return [...s].sort();
  }, [baseCurrency, quoteCurrencies]);

  return useQuery({
    queryKey: [...keys.frankfurter, "v2", "rates", baseCurrency, sortedUniqueQuotes.join(",")],
    queryFn: () => fetchFrankfurterRatesToBase(baseCurrency, sortedUniqueQuotes),
    enabled: sortedUniqueQuotes.length > 0,
    staleTime: 1000 * 60 * 60 * 4,
    gcTime: 1000 * 60 * 60 * 12,
  });
}
