/** Draft rows use this id. It is never a stored record id. */
export const DRAFT_RECORD_ID = "new";

export function readExpandedParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get(name);
  if (!value) return null;
  return value;
}

/** Writes `name` into the query string without dropping other params. Draft id `new` is kept so a refresh reopens create. */
export function writeExpandedParam(name: string, id: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) url.searchParams.set(name, id);
  else url.searchParams.delete(name);
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(null, "", next);
}
