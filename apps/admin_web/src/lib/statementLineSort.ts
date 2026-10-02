/** Instant used to order statement rows. `sortUtc` wins when present. */
export function statementLineSortTimeMs(line: {
  readonly dateUtc: string;
  readonly sortUtc?: string;
}): number {
  const raw = line.sortUtc?.trim() || line.dateUtc;
  const time = new Date(raw).getTime();
  return Number.isNaN(time) ? 0 : time;
}

export function compareStatementLinesNewestFirst(
  a: { readonly dateUtc: string; readonly sortUtc?: string },
  b: { readonly dateUtc: string; readonly sortUtc?: string },
): number {
  return statementLineSortTimeMs(b) - statementLineSortTimeMs(a);
}
