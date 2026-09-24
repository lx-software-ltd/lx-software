/** Draft rows use this id. It is never a stored record id. */
export const DRAFT_RECORD_ID = "new";

/** Row-editor params. House and statement lines use `${key}-line`. */
const EXPANDED_PARAM_NAMES = new Set([
  "account",
  "liability",
  "income",
  "expenses",
  "investment",
  "savings",
  "pension",
  "allocation",
  "asset",
  "bank",
  "watch",
  "prospect",
]);

export function isRowExpandedParam(name: string): boolean {
  return EXPANDED_PARAM_NAMES.has(name) || name.endsWith("-line");
}

export function readExpandedParam(name: string): string | null {
  if (typeof window === "undefined") return null;
  const value = new URLSearchParams(window.location.search).get(name);
  if (!value) return null;
  return value;
}

function replaceExpandedSearch(url: URL): void {
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) window.history.replaceState(null, "", next);
}

/** Removes every row-editor param except `keep`. */
export function clearExpandedParamsExcept(keep: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const key of [...url.searchParams.keys()]) {
    if (key !== keep && isRowExpandedParam(key)) url.searchParams.delete(key);
  }
  replaceExpandedSearch(url);
}

/**
 * Writes `name` into the query string and drops every other row-editor param.
 * Draft id `new` is kept so a refresh reopens create. Non-row params stay.
 */
export function writeExpandedParam(name: string, id: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  for (const key of [...url.searchParams.keys()]) {
    if (key !== name && isRowExpandedParam(key)) url.searchParams.delete(key);
  }
  if (id) url.searchParams.set(name, id);
  else url.searchParams.delete(name);
  replaceExpandedSearch(url);
}
