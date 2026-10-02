import { useCallback, useState } from "react";
import type { SortDir } from "../lib/compareBy";

export function useSortState<K extends string>(initialKey: K | null, initialDir: SortDir = "asc") {
  const [sortKey, setSortKey] = useState<K | null>(initialKey);
  const [sortDir, setSortDir] = useState<SortDir>(initialDir);

  const onSort = useCallback((key: K) => {
    setSortKey((prevKey) => {
      if (prevKey !== key) {
        setSortDir("asc");
        return key;
      }
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return prevKey;
    });
  }, []);

  const ariaSort = useCallback(
    (key: K): "ascending" | "descending" | "none" | undefined => {
      if (sortKey === null) return undefined;
      if (sortKey === key) return sortDir === "asc" ? "ascending" : "descending";
      return "none";
    },
    [sortDir, sortKey],
  );

  const directionFor = useCallback(
    (key: K): SortDir | null => (sortKey === key ? sortDir : null),
    [sortDir, sortKey],
  );

  return { sortKey, sortDir, onSort, ariaSort, directionFor };
}
