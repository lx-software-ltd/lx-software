import { EXPENSE_CATEGORIES, type HouseKey } from "../financeTypes";
import { allocationRecordIncomeMonthlyValue } from "./allocations";
import type {
  ExpenseIncomeAllocationPercents,
  FinanceAccountType,
  FinanceAllocationRecord,
  FinanceInvestmentRecord,
  FinanceLedgerAmountBuckets,
  FinanceLedgerRecord,
  FinanceLiabilityRecord,
} from "./types";
import { DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS } from "./types";


/**
 * Per-house property equity: Real Estate investments linked to the house
 * (current value, falling back to principal) minus liabilities linked to the
 * house, grouped by currency. No FX conversion — houses are normally
 * single-currency, and mixed currencies stay visible as separate rows.
 */
export function housePropertyEquityByCurrency(
  investments: readonly FinanceInvestmentRecord[],
  liabilities: readonly FinanceLiabilityRecord[],
  houseKey: HouseKey,
): {
  readonly valueByCurrency: Readonly<Record<string, number>>;
  readonly liabilitiesByCurrency: Readonly<Record<string, number>>;
  readonly equityByCurrency: Readonly<Record<string, number>>;
} {
  const valueByCurrency: Record<string, number> = {};
  const liabilitiesByCurrency: Record<string, number> = {};
  const equityByCurrency: Record<string, number> = {};
  for (const r of investments) {
    if (r.category !== "Real Estate" || r.relatedHouse !== houseKey) continue;
    const v = r.currentValue ?? r.principalAmount;
    valueByCurrency[r.currency] = (valueByCurrency[r.currency] ?? 0) + v;
    equityByCurrency[r.currency] = (equityByCurrency[r.currency] ?? 0) + v;
  }
  for (const l of liabilities) {
    if (l.relatedHouse !== houseKey) continue;
    liabilitiesByCurrency[l.currency] =
      (liabilitiesByCurrency[l.currency] ?? 0) + l.outstandingBalance;
    equityByCurrency[l.currency] =
      (equityByCurrency[l.currency] ?? 0) - l.outstandingBalance;
  }
  return { valueByCurrency, liabilitiesByCurrency, equityByCurrency };
}


/**
 * Signed balance for the Accounts tab FX total: bank and debit add; credit card subtracts
 * (current balance is treated as debt).
 */
export function financeAccountSignedValueForTotal(
  accountType: FinanceAccountType,
  recordedValue: number,
): number {
  return accountType === "Credit Card" ? -recordedValue : recordedValue;
}


/** Monthly equivalent for ledger tables that show a per-month column. */
export function ledgerMonthlyAmount(record: FinanceLedgerRecord): number {
  return record.amountPeriod === "year" ? record.amount / 12 : record.amount;
}


export function normalizeExpenseIncomeAllocationPercents(
  input: unknown,
): ExpenseIncomeAllocationPercents {
  const d = DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS;
  if (!input || typeof input !== "object") {
    return d;
  }
  const o = input as Record<string, unknown>;
  const clamp = (v: unknown): number => {
    const n =
      typeof v === "number"
        ? v
        : typeof v === "string"
          ? Number.parseFloat(v)
          : Number.NaN;
    if (!Number.isFinite(n)) {
      return 0;
    }
    return Math.min(100, Math.max(0, n));
  };
  return {
    taxOnIncomePercent: clamp(o.taxOnIncomePercent),
    investmentOnIncomePercent: clamp(o.investmentOnIncomePercent),
    savingOnIncomePercent: clamp(o.savingOnIncomePercent),
  };
}


type DerivedExpenseFromTaggedIncomeSpec = {
  readonly idSegment: string;
  readonly category: "Tax" | "Investment" | "Saving";
  readonly title: string;
  readonly incomeFlag: "isTax" | "isInvestment" | "isSaving";
  readonly percentKey: keyof ExpenseIncomeAllocationPercents;
};


const DERIVED_EXPENSE_FROM_TAGGED_INCOME_SPECS: readonly DerivedExpenseFromTaggedIncomeSpec[] = [
  {
    idSegment: "tax-on-income",
    category: "Tax",
    title: "Tax on Income",
    incomeFlag: "isTax",
    percentKey: "taxOnIncomePercent",
  },
  {
    idSegment: "investment-on-income",
    category: "Investment",
    title: "Investments on Income",
    incomeFlag: "isInvestment",
    percentKey: "investmentOnIncomePercent",
  },
  {
    idSegment: "saving-on-income",
    category: "Saving",
    title: "Savings on Income",
    incomeFlag: "isSaving",
    percentKey: "savingOnIncomePercent",
  },
];


function isLedgerRelatedHouse(relatedHouse: HouseKey | undefined): relatedHouse is HouseKey {
  return relatedHouse === "hillmarton" || relatedHouse === "morrison";
}


function sumMonthlyTaggedIncomeByHouseAndCurrency(
  incomeRecords: readonly FinanceLedgerRecord[],
  houseKey: HouseKey,
  flag: "isTax" | "isSaving" | "isInvestment",
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of incomeRecords) {
    if (r.amountPeriod !== "month" || r.relatedHouse !== houseKey) {
      continue;
    }
    if (!r[flag]) {
      continue;
    }
    const c = r.currency;
    out[c] = (out[c] ?? 0) + ledgerMonthlyAmount(r);
  }
  return out;
}


/** Tagged monthly income rows with no (or invalid) related property — still counts toward derived rows. */
function sumMonthlyTaggedIncomeWithoutRelatedHouseByCurrency(
  incomeRecords: readonly FinanceLedgerRecord[],
  flag: "isTax" | "isSaving" | "isInvestment",
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of incomeRecords) {
    if (r.amountPeriod !== "month" || !r[flag]) {
      continue;
    }
    if (isLedgerRelatedHouse(r.relatedHouse)) {
      continue;
    }
    const c = r.currency;
    out[c] = (out[c] ?? 0) + ledgerMonthlyAmount(r);
  }
  return out;
}


/**
 * Synthetic expense rows from allocation rates × monthly income flagged on the income sheet
 * (Tax / Investment / Saving), one row per property and currency where the tagged base is
 * positive and the rate is greater than zero, plus rows for tagged income with no related
 * property.
 */
export function buildDerivedExpenseLedgerRowsFromTaggedIncome(
  incomeRecords: readonly FinanceLedgerRecord[],
  percents: ExpenseIncomeAllocationPercents,
  relatedHouseOptions: ReadonlyArray<{ readonly value: HouseKey; readonly label: string }>,
): FinanceLedgerRecord[] {
  const houses: readonly HouseKey[] = ["hillmarton", "morrison"];
  const out: FinanceLedgerRecord[] = [];
  for (const houseKey of houses) {
    const houseLabel =
      relatedHouseOptions.find((o) => o.value === houseKey)?.label ?? houseKey;
    for (const spec of DERIVED_EXPENSE_FROM_TAGGED_INCOME_SPECS) {
      const pct = percents[spec.percentKey];
      if (pct <= 0) {
        continue;
      }
      const byCcy = sumMonthlyTaggedIncomeByHouseAndCurrency(
        incomeRecords,
        houseKey,
        spec.incomeFlag,
      );
      for (const [currency, base] of Object.entries(byCcy)) {
        if (base <= 0) {
          continue;
        }
        const amount = base * (pct / 100);
        if (!Number.isFinite(amount) || amount === 0) {
          continue;
        }
        out.push({
          id: `__derived__${spec.idSegment}__${houseKey}__${currency}`,
          category: spec.category,
          description: `${spec.title} (${houseLabel})`,
          amount,
          currency,
          amountPeriod: "month",
          relatedHouse: houseKey,
          isDerivedFromTaggedIncome: true,
        });
      }
    }
  }
  for (const spec of DERIVED_EXPENSE_FROM_TAGGED_INCOME_SPECS) {
    const pct = percents[spec.percentKey];
    if (pct <= 0) {
      continue;
    }
    const byCcy = sumMonthlyTaggedIncomeWithoutRelatedHouseByCurrency(
      incomeRecords,
      spec.incomeFlag,
    );
    for (const [currency, base] of Object.entries(byCcy)) {
      if (base <= 0) {
        continue;
      }
      const amount = base * (pct / 100);
      if (!Number.isFinite(amount) || amount === 0) {
        continue;
      }
      out.push({
        id: `__derived__${spec.idSegment}__unallocated__${currency}`,
        category: spec.category,
        description: `${spec.title} (no related property)`,
        amount,
        currency,
        amountPeriod: "month",
        isDerivedFromTaggedIncome: true,
      });
    }
  }
  return out;
}


/**
 * Sums Finance Income / Expenses ledger rows with `amountPeriod` **month** and
 * `relatedHouse` equal to `houseKey`. Yearly rows are excluded. All matching
 * rows are included (no calendar-year filter).
 *
 * Derived tax / investment / saving expense slices apply only to monthly income
 * rows **linked to this house**. Tagged income with no related property is not
 * attributed here (see synthetic rows from {@link buildDerivedExpenseLedgerRowsFromTaggedIncome}).
 *
 * When `allocationRecords` is set, allocations tagged as income with the same
 * `relatedHouse` add to the income side (mirrors the Income tab).
 */
export function sumMonthlyFinanceLedgerAmountsByHouse(
  incomeRecords: readonly FinanceLedgerRecord[],
  expenseRecords: readonly FinanceLedgerRecord[],
  houseKey: HouseKey,
  expenseAllocationPercents?: ExpenseIncomeAllocationPercents,
  allocationRecords?: readonly FinanceAllocationRecord[],
): FinanceLedgerAmountBuckets {
  const alloc = expenseAllocationPercents ?? DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS;
  const income: Record<string, number> = {};
  const expenses: Record<string, number> = {};

  for (const r of incomeRecords) {
    if (r.amountPeriod !== "month" || r.relatedHouse !== houseKey) continue;
    const c = r.currency;
    income[c] = (income[c] ?? 0) + r.amount;
  }
  if (allocationRecords?.length) {
    for (const a of allocationRecords) {
      if (a.relatedHouse !== houseKey) continue;
      const m = allocationRecordIncomeMonthlyValue(a);
      if (!Number.isFinite(m) || m <= 0) continue;
      const c = a.currency;
      income[c] = (income[c] ?? 0) + m;
    }
  }
  for (const r of expenseRecords) {
    if (r.amountPeriod !== "month" || r.relatedHouse !== houseKey) continue;
    const c = r.currency;
    expenses[c] = (expenses[c] ?? 0) + r.amount;
  }

  const addDerivedForFlag = (
    flag: "isTax" | "isSaving" | "isInvestment",
    pct: number,
  ): void => {
    if (pct <= 0) {
      return;
    }
    for (const r of incomeRecords) {
      if (r.amountPeriod !== "month" || r.relatedHouse !== houseKey) {
        continue;
      }
      if (!r[flag]) {
        continue;
      }
      const c = r.currency;
      const base = ledgerMonthlyAmount(r);
      expenses[c] = (expenses[c] ?? 0) + base * (pct / 100);
    }
  };

  addDerivedForFlag("isTax", alloc.taxOnIncomePercent);
  addDerivedForFlag("isInvestment", alloc.investmentOnIncomePercent);
  addDerivedForFlag("isSaving", alloc.savingOnIncomePercent);

  return { incomeByCurrency: income, expensesByCurrency: expenses };
}


/**
 * Monthly ledger totals for income and expenses not linked to a property
 * (`relatedHouse` unset), plus synthetic derived expense rows from tagged
 * monthly income with no related property (same rules as the expenses sheet).
 * Yearly (`amountPeriod: year`) rows are excluded, matching
 * {@link sumMonthlyFinanceLedgerAmountsByHouse}.
 *
 * When `allocationRecords` is set, allocations tagged as income with no related
 * property add to the general income side.
 */
export function sumMonthlyFinanceLedgerAmountsGeneral(
  incomeRecords: readonly FinanceLedgerRecord[],
  expenseRecords: readonly FinanceLedgerRecord[],
  expenseAllocationPercents: ExpenseIncomeAllocationPercents,
  relatedHouseOptions: ReadonlyArray<{ readonly value: HouseKey; readonly label: string }>,
  allocationRecords?: readonly FinanceAllocationRecord[],
): FinanceLedgerAmountBuckets {
  const alloc = expenseAllocationPercents ?? DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS;
  const income: Record<string, number> = {};
  const expenses: Record<string, number> = {};

  for (const r of incomeRecords) {
    if (r.amountPeriod !== "month" || isLedgerRelatedHouse(r.relatedHouse)) {
      continue;
    }
    const c = r.currency;
    income[c] = (income[c] ?? 0) + r.amount;
  }
  if (allocationRecords?.length) {
    for (const a of allocationRecords) {
      if (isLedgerRelatedHouse(a.relatedHouse)) continue;
      const m = allocationRecordIncomeMonthlyValue(a);
      if (!Number.isFinite(m) || m <= 0) continue;
      const c = a.currency;
      income[c] = (income[c] ?? 0) + m;
    }
  }
  for (const r of expenseRecords) {
    if (r.amountPeriod !== "month" || isLedgerRelatedHouse(r.relatedHouse)) {
      continue;
    }
    const c = r.currency;
    expenses[c] = (expenses[c] ?? 0) + r.amount;
  }

  const derived = buildDerivedExpenseLedgerRowsFromTaggedIncome(
    incomeRecords,
    alloc,
    relatedHouseOptions,
  );
  for (const r of derived) {
    if (isLedgerRelatedHouse(r.relatedHouse)) {
      continue;
    }
    const c = r.currency;
    expenses[c] = (expenses[c] ?? 0) + r.amount;
  }

  return { incomeByCurrency: income, expensesByCurrency: expenses };
}


/**
 * Per-currency monthly expense totals for the **general** ledger slice (no related
 * property), matching {@link sumMonthlyFinanceLedgerAmountsGeneral}: persisted
 * expense rows with `amountPeriod: month` and no `relatedHouse`, plus derived
 * tax / saving / investment rows from tagged income with no related property.
 * Every {@link EXPENSE_CATEGORIES} key is present; currencies with zero net are omitted.
 */
export function sumMonthlyGeneralExpenseAmountsByCategory(
  incomeRecords: readonly FinanceLedgerRecord[],
  expenseRecords: readonly FinanceLedgerRecord[],
  expenseAllocationPercents: ExpenseIncomeAllocationPercents,
  relatedHouseOptions: ReadonlyArray<{ readonly value: HouseKey; readonly label: string }>,
): Readonly<Record<string, Readonly<Record<string, number>>>> {
  const alloc = expenseAllocationPercents ?? DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS;
  const byCat: Record<string, Record<string, number>> = {};
  for (const cat of EXPENSE_CATEGORIES) {
    byCat[cat] = {};
  }

  for (const r of expenseRecords) {
    if (r.amountPeriod !== "month" || isLedgerRelatedHouse(r.relatedHouse)) {
      continue;
    }
    const bucket = byCat[r.category];
    if (!bucket) {
      continue;
    }
    const c = r.currency;
    bucket[c] = (bucket[c] ?? 0) + r.amount;
  }

  const derived = buildDerivedExpenseLedgerRowsFromTaggedIncome(
    incomeRecords,
    alloc,
    relatedHouseOptions,
  );
  for (const r of derived) {
    if (isLedgerRelatedHouse(r.relatedHouse)) {
      continue;
    }
    const bucket = byCat[r.category];
    if (!bucket) {
      continue;
    }
    const c = r.currency;
    bucket[c] = (bucket[c] ?? 0) + r.amount;
  }

  return byCat;
}


/** Per-currency income minus expenses for {@link FinanceLedgerAmountBuckets}. */
export function monthlyLedgerNetByCurrency(
  buckets: FinanceLedgerAmountBuckets,
): Record<string, number> {
  const { incomeByCurrency: inc, expensesByCurrency: exp } = buckets;
  const keys = [...new Set([...Object.keys(inc), ...Object.keys(exp)])];
  const out: Record<string, number> = {};
  for (const c of keys) {
    out[c] = (inc[c] ?? 0) - (exp[c] ?? 0);
  }
  return out;
}
