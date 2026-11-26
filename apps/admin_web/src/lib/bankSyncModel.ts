/**
 * Types for the Enable Banking sync feature (see
 * `backend/lambda/admin/bank_sync.py` for the API contract).
 */

export const BANKING_CALLBACK_PATH = "/v1/admin/banking/callback";

export type BankSyncAccount = {
  readonly uid: string;
  readonly identifier?: string;
  readonly name?: string;
  readonly product?: string;
  readonly currency?: string;
};

export type BankSyncSession = {
  readonly sessionId: string;
  readonly bankName: string;
  readonly bankCountry: string;
  readonly validUntil?: string;
  readonly createdAt?: string;
  readonly accounts: readonly BankSyncAccount[];
};

export type BankSyncMapping = {
  readonly accountUid: string;
  readonly accountRecordId: string;
};

export type BankSyncResult = {
  readonly accountUid: string;
  readonly accountRecordId: string;
  readonly status: "ok" | "error";
  readonly balance?: number;
  readonly currency?: string;
  readonly balanceType?: string;
  readonly message?: string;
};

export type BankSyncReport = {
  readonly at: string;
  readonly results: readonly BankSyncResult[];
};

export type BankSyncState = {
  readonly enabled: boolean;
  readonly callbackPath: string;
  readonly sessions: readonly BankSyncSession[];
  readonly mappings: readonly BankSyncMapping[];
  readonly lastSync: BankSyncReport | null;
};

export type BankOption = {
  readonly name: string;
  readonly country: string;
  readonly logo?: string | null;
  readonly beta: boolean;
  readonly maximumConsentValidity?: number | null;
};

/** Countries offered in the "Connect a bank" picker (Enable Banking covers the EEA + UK). */
export const BANK_CONNECT_COUNTRIES: readonly {
  readonly code: string;
  readonly label: string;
}[] = [
  { code: "GB", label: "United Kingdom" },
  { code: "DE", label: "Germany" },
  { code: "FR", label: "France" },
  { code: "ES", label: "Spain" },
  { code: "IT", label: "Italy" },
  { code: "IE", label: "Ireland" },
  { code: "NL", label: "Netherlands" },
  { code: "BE", label: "Belgium" },
  { code: "AT", label: "Austria" },
  { code: "PT", label: "Portugal" },
  { code: "FI", label: "Finland" },
  { code: "SE", label: "Sweden" },
  { code: "DK", label: "Denmark" },
  { code: "NO", label: "Norway" },
  { code: "PL", label: "Poland" },
  { code: "EE", label: "Estonia" },
  { code: "LT", label: "Lithuania" },
  { code: "LV", label: "Latvia" },
];

/** Consents this close to expiry are flagged so the owner re-authorises before sync stops. */
export const CONSENT_EXPIRY_WARNING_DAYS = 14;

/**
 * Whole days until a PSD2 consent expires (negative once expired); null when
 * the session has no `validUntil` or it is not a parseable instant.
 */
export function consentDaysRemaining(validUntil: string | undefined, now = new Date()): number | null {
  if (!validUntil) return null;
  const end = Date.parse(validUntil);
  if (!Number.isFinite(end)) return null;
  return Math.floor((end - now.getTime()) / 86_400_000);
}

/** Human label for a linked bank account row. */
export function bankAccountLabel(account: BankSyncAccount): string {
  const parts: string[] = [];
  if (account.name) parts.push(account.name);
  else if (account.product) parts.push(account.product);
  if (account.identifier) parts.push(account.identifier);
  return parts.length > 0 ? parts.join(" · ") : account.uid;
}
