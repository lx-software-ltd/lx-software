/**
 * Statement rows read newest document date first, with the id as a stable
 * tie-break. Mirrored books (Evolve Sprouts) follow the product's Finance Tax
 * panel, which orders by document date too.
 */
export function compareStatementLinesNewestFirst(
  a: { readonly id: string; readonly dateUtc: string },
  b: { readonly id: string; readonly dateUtc: string },
): number {
  const byDate = statementLineTimeMs(b) - statementLineTimeMs(a);
  if (byDate !== 0) return byDate;
  return a.id.localeCompare(b.id);
}

function statementLineTimeMs(line: { readonly dateUtc: string }): number {
  const time = new Date(line.dateUtc).getTime();
  return Number.isNaN(time) ? 0 : time;
}
