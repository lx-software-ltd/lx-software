/** Finance domain types and category constants (from contracts/finance.json). */

export {
  ASSET_TYPES,
  EXPENSE_CATEGORIES,
  FINANCE_ACCOUNT_TYPES,
  FINANCE_HOUSE_KEYS,
  FINANCE_LIABILITY_TYPES,
  FINANCE_STATEMENT_BOOK_KEYS,
  MIRRORED_STATEMENT_BOOK_KEYS,
  STATEMENT_BOOK_LABELS,
  GLOBAL_DEFAULT_CURRENCY,
  INCOME_CATEGORIES,
  INVESTMENT_CATEGORIES,
  MAX_ACCOUNT_DESCRIPTION_LEN,
  MAX_INVESTMENT_CRYPTO_CURRENCY_LEN,
  MAX_INVESTMENT_TICKER_LEN,
  MAX_PENSION_DESCRIPTION_LEN,
  type CurrencyCode,
  type HouseKey,
  type StatementBookKey,
  type StatementOwnerKey,
} from "./contracts/generated";

/** Legacy aliases used across finance UI code. */
export {
  MAX_INVESTMENT_CRYPTO_CURRENCY_LEN as INVESTMENT_CRYPTO_CURRENCY_MAX_LEN,
  MAX_INVESTMENT_TICKER_LEN as INVESTMENT_TICKER_MAX_LEN,
} from "./contracts/generated";

import {
  ASSET_TYPES,
  FINANCE_ACCOUNT_TYPES,
  FINANCE_LIABILITY_TYPES,
  INVESTMENT_CATEGORIES,
  type CurrencyCode,
} from "./contracts/generated";

export type FinanceLineType = "income" | "expenditure" | "mortgage";

export type HouseFloat = {
  readonly amount: number;
  readonly currency: string;
};

export type HouseStatementLine = {
  readonly id: string;
  readonly dateUtc: string;
  /** When set, tables sort by this instant instead of `dateUtc`. */
  readonly sortUtc?: string;
  readonly type: FinanceLineType;
  readonly description: string;
  readonly netAmount: number;
  readonly vat: number;
  readonly currency: string;
  readonly grossAmount: number;
  readonly sourceAssetKeys?: readonly string[];
};

export type HouseFinanceData = {
  readonly defaultCurrency: CurrencyCode;
  readonly float: HouseFloat;
  readonly lines: readonly HouseStatementLine[];
};

export type InvestmentCategory = (typeof INVESTMENT_CATEGORIES)[number];
export type AssetType = (typeof ASSET_TYPES)[number];
export type FinanceAccountType = (typeof FINANCE_ACCOUNT_TYPES)[number];
export type FinanceLiabilityType = (typeof FINANCE_LIABILITY_TYPES)[number];
