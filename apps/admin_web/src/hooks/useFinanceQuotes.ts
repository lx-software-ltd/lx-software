import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { fetchFinanceQuotes, type FinanceQuoteResult } from "../lib/financeQuotes";

/**
 * Live ticker / crypto spot prices via the admin `/v1/admin/finance/quotes` proxy.
 * Returns `[]` (and keeps the query disabled, no network) when `symbols` is empty.
 */
export function useFinanceQuotes(symbols: readonly string[]) {
  const sortedUnique = useMemo(() => {
    const s = new Set<string>();
    for (const raw of symbols) {
      const t = raw.trim();
      if (t) s.add(t);
    }
    return [...s].sort();
  }, [symbols]);

  return useQuery<readonly FinanceQuoteResult[], Error>({
    queryKey: ["finance-quotes", sortedUnique.join(",")],
    queryFn: () => fetchFinanceQuotes(sortedUnique),
    enabled: sortedUnique.length > 0,
    // Spot prices move continuously; refresh every 5 minutes and don't cache forever.
    staleTime: 1000 * 60 * 5,
    gcTime: 1000 * 60 * 30,
    refetchOnWindowFocus: false,
  });
}
