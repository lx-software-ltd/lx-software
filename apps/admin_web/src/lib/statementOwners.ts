import {
  FINANCE_HOUSE_KEYS,
  FINANCE_STATEMENT_BOOK_KEYS,
  MIRRORED_STATEMENT_BOOK_KEYS,
  STATEMENT_BOOK_LABELS,
  type HouseKey,
  type StatementBookKey,
  type StatementOwnerKey,
} from "./financeTypes";

export const SIU_TIN_DEI_BOOK_KEY: StatementBookKey = "siuTinDei";
export const LX_SOFTWARE_BOOK_KEY: StatementBookKey = "lxSoftware";
export const EVOLVE_SPROUTS_BOOK_KEY: StatementBookKey = "evolveSprouts";

export const STATEMENT_BOOK_DISPLAY_LABEL = STATEMENT_BOOK_LABELS;

/** Product books on the main dashboard: LX Software, then the remaining books. */
export const STATEMENT_BOOK_DASHBOARD_ORDER: readonly StatementBookKey[] = [
  LX_SOFTWARE_BOOK_KEY,
  ...FINANCE_STATEMENT_BOOK_KEYS.filter((key) => key !== LX_SOFTWARE_BOOK_KEY),
];

export function isMirroredStatementBook(bookKey: StatementBookKey): boolean {
  return (MIRRORED_STATEMENT_BOOK_KEYS as readonly string[]).includes(bookKey);
}

export function isHouseKey(value: string): value is HouseKey {
  return (FINANCE_HOUSE_KEYS as readonly string[]).includes(value);
}

export function isStatementBookKey(value: string): value is StatementBookKey {
  return (FINANCE_STATEMENT_BOOK_KEYS as readonly string[]).includes(value);
}

export function statementOwnerQueryKey(
  owner: StatementOwnerKey,
): readonly string[] {
  return isHouseKey(owner) ? ["finance"] : [owner];
}

export function parseStatementStartPath(owner: StatementOwnerKey): string {
  return isHouseKey(owner)
    ? `/finance/${owner}/parse-statement`
    : `/${kebabBookKey(owner)}/parse-statement`;
}

export function parseStatementJobPath(
  owner: StatementOwnerKey,
  jobId: string,
): string {
  return isHouseKey(owner)
    ? `/finance/${owner}/parse-statement/jobs/${encodeURIComponent(jobId)}`
    : `/${kebabBookKey(owner)}/parse-statement/jobs/${encodeURIComponent(jobId)}`;
}

export function kebabBookKey(owner: StatementBookKey): string {
  return owner.replace(/[A-Z]/g, (ch) => `-${ch.toLowerCase()}`);
}

export function statementBookApiPath(owner: StatementBookKey): string {
  return `/${kebabBookKey(owner)}`;
}

export function financeOwnerDisplayLabel(owner?: string): string {
  if (!owner?.trim()) return "—";
  if (isStatementBookKey(owner)) return STATEMENT_BOOK_DISPLAY_LABEL[owner];
  return owner;
}
