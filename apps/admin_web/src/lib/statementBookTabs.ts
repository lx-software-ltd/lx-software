export type StatementBookTab = "dashboard" | "expenses" | "gains" | "board";

const EXPLICIT_BOOK_TABS = new Set<StatementBookTab>(["dashboard", "expenses", "gains"]);

/** Siu Tin Dei opens Executive Board unless `?tab=` names another book tab. */
export function defaultStatementBookTab(
  hasExecutiveBoard: boolean,
  search: string,
): StatementBookTab {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const requested = params.get("tab");
  if (requested && EXPLICIT_BOOK_TABS.has(requested as StatementBookTab)) {
    return requested as StatementBookTab;
  }
  if (hasExecutiveBoard) return "board";
  return "dashboard";
}
