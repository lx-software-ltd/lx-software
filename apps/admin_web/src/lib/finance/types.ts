export {
  ASSET_TYPES,
  EXPENSE_CATEGORIES,
  FINANCE_ACCOUNT_TYPES,
  FINANCE_HOUSE_KEYS,
  FINANCE_LIABILITY_TYPES,
  FINANCE_STATEMENT_BOOK_KEYS,
  INCOME_CATEGORIES,
  INVESTMENT_CATEGORIES,
  INVESTMENT_CRYPTO_CURRENCY_MAX_LEN,
  INVESTMENT_TICKER_MAX_LEN,
  MAX_ACCOUNT_DESCRIPTION_LEN,
  MAX_PENSION_DESCRIPTION_LEN,
  type AssetType,
  type FinanceAccountType,
  type FinanceLiabilityType,
  type HouseKey,
  type InvestmentCategory,
  type StatementBookKey,
  type StatementOwnerKey,
} from "../financeTypes";

import { GLOBAL_DEFAULT_CURRENCY } from "../currencies";
import type {
  AssetType,
  CurrencyCode,
  FinanceAccountType,
  FinanceLiabilityType,
  HouseKey,
  InvestmentCategory,
} from "../financeTypes";


export type FinanceLineType = "income" | "expenditure" | "mortgage";


export type HouseFloat = {
  readonly amount: number;
  readonly currency: string;
};


export type HouseStatementLine = {
  readonly id: string;
  /** ISO 8601 instant (UTC), e.g. 2026-05-08T14:30:00.000Z */
  readonly dateUtc: string;
  readonly type: FinanceLineType;
  readonly description: string;
  readonly netAmount: number;
  readonly vat: number;
  readonly currency: string;
  readonly grossAmount: number;
  /**
   * Optional S3 object keys for assets (e.g. statement PDFs) tied to this line.
   * Populated by imports and optional manual uploads. Legacy records may only
   * have `sourceAssetKey` in JSON until they are saved again.
   */
  readonly sourceAssetKeys?: readonly string[];
};


export type HouseFinanceData = {
  /** House-level default for new money fields and unsupported legacy codes. */
  readonly defaultCurrency: CurrencyCode;
  readonly float: HouseFloat;
  readonly lines: readonly HouseStatementLine[];
};


/** Optional income ledger toggles (stored on income sheet rows only). */
export type IncomeLedgerFlagField = "isTax" | "isSaving" | "isInvestment";


export const INCOME_LEDGER_FLAG_FIELDS: ReadonlyArray<{
  readonly field: IncomeLedgerFlagField;
  readonly label: string;
}> = [
  { field: "isTax", label: "Tax" },
  { field: "isSaving", label: "Saving" },
  { field: "isInvestment", label: "Investment" },
];


/** Expense ledger only: tag shown on Expenses tab and drives the Allocations tab. */
export type ExpenseLedgerFlagField = "isAllocate";


export const EXPENSE_LEDGER_FLAG_FIELDS: ReadonlyArray<{
  readonly field: ExpenseLedgerFlagField;
  readonly label: string;
}> = [{ field: "isAllocate", label: "Allocate" }];


/** One row in the Investments sheet (DynamoDB finance sheet `investments`). */
export type FinanceInvestmentRecord = {
  readonly id: string;
  readonly category: InvestmentCategory;
  readonly currency: string;
  readonly assetType: AssetType;
  readonly provider: string;
  /** Amount in `currency`: invested principal; for Crypto with `unit`, spot fiat value of one unit. */
  readonly principalAmount: number;
  /** Optional quantity (e.g. shares, coins, lots). */
  readonly unit?: number;
  /** When category is Real Estate, optional link to a house (same keys as finance house tabs). */
  readonly relatedHouse?: HouseKey;
  /**
   * When category is Real Estate, optional market/appraisal value in `currency` for totals and FX.
   * When omitted, {@link principalAmount} is used as the quote-currency notional.
   */
  readonly currentValue?: number;
  /** When category is ETF, optional ticker symbol or name. */
  readonly ticker?: string;
  /** When category is Crypto, optional asset name (e.g. coin); UI label “Crypto currency”. */
  readonly cryptoCurrency?: string;
  /** UTC calendar date `YYYY-MM-DD` when row content last changed (set by admin API). */
  readonly lastUpdated?: string;
};


/** One row in the Savings sheet (DynamoDB finance sheet `savings`). */
export type FinanceSavingsRecord = {
  readonly id: string;
  readonly deposit: string;
  readonly assetType: AssetType;
  readonly description: string;
  readonly value: number;
  readonly currency: string;
};


/** One row in the Pension sheet (DynamoDB finance sheet `pension`). */
export type FinancePensionRecord = {
  readonly id: string;
  readonly fund: string;
  readonly description: string;
  readonly value: number;
  readonly currency: string;
  /** UTC calendar date `YYYY-MM-DD` when row content last changed (set by admin API). */
  readonly lastUpdated?: string;
};


/** One row in the Accounts sheet (DynamoDB finance sheet `accounts`). */
export type FinanceAccountRecord = {
  readonly id: string;
  readonly description: string;
  readonly accountType: FinanceAccountType;
  /** Day of month (1–31) for the billing cycle. */
  readonly billingCycleDay: number;
  /** Current balance in `currency` (stored as `recordedValue` in the admin API). */
  readonly recordedValue: number;
  /**
   * Credit Card only: last statement balance in `currency`.
   * Omitted for other account types.
   */
  readonly lastStatementAmount?: number;
  readonly currency: string;
  /** UTC calendar date `YYYY-MM-DD` when row content last changed (set by admin API). */
  readonly lastUpdated?: string;
};


/** One row in the Liabilities sheet (DynamoDB finance sheet `liabilities`). */
export type FinanceLiabilityRecord = {
  readonly id: string;
  readonly description: string;
  readonly liabilityType: FinanceLiabilityType;
  /** Remaining principal owed in `currency` (always ≥ 0). */
  readonly outstandingBalance: number;
  readonly currency: string;
  /** Optional annual interest rate, 0–100. */
  readonly interestRatePercent?: number;
  /** Optional link to a house (e.g. its mortgage) for per-property equity. */
  readonly relatedHouse?: HouseKey;
  /** UTC calendar date `YYYY-MM-DD` when row content last changed (set by admin API). */
  readonly lastUpdated?: string;
};


/**
 * One row on the Allocations tab: mirrors an expense tagged Allocate, with a persisted
 * accumulated amount (DynamoDB finance sheet `allocations`).
 */
export type FinanceAllocationRecord = {
  readonly expenseId: string;
  readonly description: string;
  /**
   * Linked rows: monthly amount from the expense ledger (yearly ÷12).
   * Custom rows: always 0 (use {@link allocationRecordIncomeMonthlyValue} when tagged as income).
   */
  readonly monthlyAmount: number;
  readonly accumulatedAmount: number;
  readonly currency: string;
  /** UTC calendar date `YYYY-MM-DD` when accumulated amount last changed (set by admin API). */
  readonly lastUpdated?: string;
  /** User-defined allocation line (editable description/currency; no monthly budget). */
  readonly isCustomAllocation?: boolean;
  /**
   * When true, a synthetic income line appears on the Income tab (and in general monthly totals).
   * Custom rows require {@link allocationIncomeMonthly}; linked rows use {@link monthlyAmount}.
   */
  readonly isIncome?: boolean;
  /**
   * When true, row is tagged Pension on Allocations and listed on the Pension tab (persisted by
   * admin API).
   */
  readonly isPension?: boolean;
  /** Custom allocations only: per-month income when `isIncome` (persisted by admin API). */
  readonly allocationIncomeMonthly?: number;
  /** Linked rows only: copied from the source expense when present. */
  readonly relatedHouse?: HouseKey;
};


/** Prefix for custom allocation row ids (aligned with admin Lambda). */
export const CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX = "__custom__";


export type FinanceLedgerSheetKey = "income" | "expenses";


/** Whether `amount` is entered per calendar month or per year (yearly rows are shown ÷12 in monthly views). */
export type FinanceLedgerAmountPeriod = "month" | "year";


/** One row in the Income or Expenses ledger (same shape; category lists differ per sheet). */
export type FinanceLedgerRecord = {
  readonly id: string;
  readonly category: string;
  readonly description: string;
  readonly amount: number;
  readonly currency: string;
  /** Defaults to `month` when omitted (legacy rows). */
  readonly amountPeriod: FinanceLedgerAmountPeriod;
  /** Optional link to a house (same keys as finance house tabs). */
  readonly relatedHouse?: HouseKey;
  /** Income ledger only: classification toggles (stored by admin API for income sheet). */
  readonly isTax?: boolean;
  readonly isSaving?: boolean;
  readonly isInvestment?: boolean;
  /** Expense ledger only: when true, row appears on the Allocations tab (stored on expense sheet). */
  readonly isAllocate?: boolean;
  /**
   * Client-only: expense rows computed from tagged monthly income and allocation rates
   * (never persisted on the expense sheet).
   */
  readonly isDerivedFromTaggedIncome?: boolean;
  /**
   * Client-only: income rows mirrored from allocations tagged as income (never persisted on the
   * income sheet).
   */
  readonly isDerivedFromAllocation?: boolean;
};


/** Percentages (0–100) applied to monthly income tagged Tax / Investment / Saving per property. */
export type ExpenseIncomeAllocationPercents = {
  readonly taxOnIncomePercent: number;
  readonly investmentOnIncomePercent: number;
  readonly savingOnIncomePercent: number;
};


export const DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS: ExpenseIncomeAllocationPercents = {
  taxOnIncomePercent: 0,
  investmentOnIncomePercent: 0,
  savingOnIncomePercent: 0,
};


/** Buckets for dashboard-style income vs expense totals by currency. */
export type FinanceLedgerAmountBuckets = {
  readonly incomeByCurrency: Readonly<Record<string, number>>;
  readonly expensesByCurrency: Readonly<Record<string, number>>;
};


export type FinancePersistedState = {
  readonly hillmarton: HouseFinanceData;
  readonly morrison: HouseFinanceData;
  readonly incomeRecords: readonly FinanceLedgerRecord[];
  readonly expenseRecords: readonly FinanceLedgerRecord[];
  readonly expenseIncomeAllocationPercents: ExpenseIncomeAllocationPercents;
  readonly investmentRecords: readonly FinanceInvestmentRecord[];
  readonly savingsRecords: readonly FinanceSavingsRecord[];
  readonly pensionRecords: readonly FinancePensionRecord[];
  readonly accountRecords: readonly FinanceAccountRecord[];
  readonly liabilityRecords: readonly FinanceLiabilityRecord[];
  readonly allocationRecords: readonly FinanceAllocationRecord[];
};


export const DEFAULT_FLOAT: HouseFloat = {
  amount: 0,
  currency: GLOBAL_DEFAULT_CURRENCY,
};


export function emptyHouse(): HouseFinanceData {
  return {
    defaultCurrency: GLOBAL_DEFAULT_CURRENCY,
    float: { ...DEFAULT_FLOAT, currency: GLOBAL_DEFAULT_CURRENCY },
    lines: [],
  };
}


export const DEFAULT_FINANCE_STATE: FinancePersistedState = {
  hillmarton: emptyHouse(),
  morrison: emptyHouse(),
  incomeRecords: [],
  expenseRecords: [],
  expenseIncomeAllocationPercents: DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS,
  investmentRecords: [],
  savingsRecords: [],
  pensionRecords: [],
  accountRecords: [],
  liabilityRecords: [],
  allocationRecords: [],
};


export type NormalizeLedgerRecordsOptions = {
  /** When true, reads `isTax` / `isSaving` / `isInvestment` for income rows (defaults false). */
  readonly includeIncomeFlags?: boolean;
  /** When true, reads `isAllocate` for expense rows (defaults false). */
  readonly includeExpenseFlags?: boolean;
};
