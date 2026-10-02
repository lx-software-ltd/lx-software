import { INCOME_CATEGORIES } from "../financeTypes";
import type { FinanceAllocationRecord, FinanceLedgerRecord } from "./types";
import { CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX } from "./types";


export function newCustomAllocationExpenseId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return `${CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX}${crypto.randomUUID()}`;
  }
  return `${CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX}line-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


/** Shapes the PUT body: linked rows omit description/currency; custom rows include them. */
export function allocationRecordsToApiPayload(
  records: readonly FinanceAllocationRecord[],
): unknown[] {
  return records.map((r) => {
    const isCustom =
      r.isCustomAllocation === true ||
      r.expenseId.startsWith(CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX);
    if (isCustom) {
      const body: Record<string, unknown> = {
        expenseId: r.expenseId,
        description: r.description,
        currency: r.currency,
        accumulatedAmount: r.accumulatedAmount,
      };
      if (r.isIncome === true) {
        body.isIncome = true;
        const m = r.allocationIncomeMonthly;
        if (typeof m === "number" && Number.isFinite(m)) {
          body.allocationIncomeMonthly = m;
        }
      }
      if (r.isPension === true) {
        body.isPension = true;
      }
      return body;
    }
    const linked: Record<string, unknown> = {
      expenseId: r.expenseId,
      accumulatedAmount: r.accumulatedAmount,
    };
    if (r.isIncome === true) {
      linked.isIncome = true;
    }
    if (r.isPension === true) {
      linked.isPension = true;
    }
    return linked;
  });
}


/** Monthly income implied by an allocation tagged {@link FinanceAllocationRecord.isIncome}. */
export function allocationRecordIncomeMonthlyValue(record: FinanceAllocationRecord): number {
  if (record.isIncome !== true) {
    return 0;
  }
  const isCustom =
    record.isCustomAllocation === true ||
    record.expenseId.startsWith(CUSTOM_ALLOCATION_EXPENSE_ID_PREFIX);
  if (isCustom) {
    const v = record.allocationIncomeMonthly;
    return typeof v === "number" && Number.isFinite(v) ? v : 0;
  }
  const v = record.monthlyAmount;
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}


/**
 * Synthetic income ledger rows for the Income tab (not persisted on the income sheet;
 * edit tags and amounts on the Allocations tab).
 */
export function syntheticIncomeLedgerRowsFromAllocations(
  allocationRecords: readonly FinanceAllocationRecord[],
): FinanceLedgerRecord[] {
  const category = INCOME_CATEGORIES[0];
  const out: FinanceLedgerRecord[] = [];
  for (const a of allocationRecords) {
    const monthly = allocationRecordIncomeMonthlyValue(a);
    if (!Number.isFinite(monthly) || monthly <= 0) {
      continue;
    }
    out.push({
      id: `__alloc_income__${a.expenseId}`,
      category,
      description: `${a.description} (allocation income)`,
      amount: monthly,
      currency: a.currency,
      amountPeriod: "month",
      ...(a.relatedHouse ? { relatedHouse: a.relatedHouse } : {}),
      isDerivedFromAllocation: true,
    });
  }
  return out;
}
