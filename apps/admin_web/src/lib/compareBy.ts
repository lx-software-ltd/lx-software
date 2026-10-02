export type SortDir = "asc" | "desc";

/**
 * Applies a sort direction to a raw comparison, then a stable tie-break.
 * `compare` must not apply the direction itself.
 */
export function compareBy<T>(
  a: T,
  b: T,
  dir: SortDir,
  compare: (left: T, right: T) => number,
  tieBreak: (left: T, right: T) => number,
): number {
  const cmp = compare(a, b);
  if (cmp !== 0) return (dir === "asc" ? 1 : -1) * cmp;
  return tieBreak(a, b);
}
