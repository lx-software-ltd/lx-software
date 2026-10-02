import {
  type QueryClient,
  type UseMutationOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useCallback } from "react";
import { adminFetchJson, getAdminApiErrorMessage } from "../lib/apiAdminClient";
import {
  type ExpenseIncomeAllocationPercents,
  type FinanceAccountRecord,
  type FinanceAllocationRecord,
  type FinanceInvestmentRecord,
  type FinanceLedgerRecord,
  type FinanceLedgerSheetKey,
  type FinanceLiabilityRecord,
  type FinancePensionRecord,
  type FinancePersistedState,
  type FinanceSavingsRecord,
  type HouseFinanceData,
  type HouseKey,
  DEFAULT_FINANCE_STATE,
  DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS,
  EXPENSE_CATEGORIES,
  INCOME_CATEGORIES,
  allocationRecordsToApiPayload,
  normalizeAllocationRecords,
  normalizeExpenseIncomeAllocationPercents,
  normalizeHouseFinanceData,
  normalizeInvestmentRecords,
  normalizeAccountRecords,
  normalizeLedgerRecords,
  normalizeLiabilityRecords,
  normalizePensionRecords,
  normalizeSavingsRecords,
} from "../lib/financeModel";
import { keys } from "../lib/queryKeys";

const LEDGER_CONFIG: Record<
  FinanceLedgerSheetKey,
  { readonly path: string; readonly bodyKey: keyof FinancePersistedState }
> = {
  income: { path: "/finance/income", bodyKey: "incomeRecords" },
  expenses: { path: "/finance/expenses", bodyKey: "expenseRecords" },
};

async function fetchFinance(): Promise<FinancePersistedState> {
  const raw = await adminFetchJson<FinancePersistedState>("/finance");
  const rawObj = raw as Record<string, unknown>;
  return {
    hillmarton: normalizeHouseFinanceData(raw.hillmarton),
    morrison: normalizeHouseFinanceData(raw.morrison),
    incomeRecords: normalizeLedgerRecords(rawObj.incomeRecords, INCOME_CATEGORIES, {
      includeIncomeFlags: true,
    }),
    expenseRecords: normalizeLedgerRecords(rawObj.expenseRecords, EXPENSE_CATEGORIES, {
      includeExpenseFlags: true,
    }),
    expenseIncomeAllocationPercents: normalizeExpenseIncomeAllocationPercents(
      rawObj.expenseIncomeAllocationPercents,
    ),
    investmentRecords: normalizeInvestmentRecords(rawObj.investmentRecords),
    savingsRecords: normalizeSavingsRecords(rawObj.savingsRecords),
    pensionRecords: normalizePensionRecords(rawObj.pensionRecords),
    accountRecords: normalizeAccountRecords(rawObj.accountRecords),
    liabilityRecords: normalizeLiabilityRecords(rawObj.liabilityRecords),
    allocationRecords: normalizeAllocationRecords(rawObj.allocationRecords),
  };
}

type PutFinanceResponse = {
  readonly data: HouseFinanceData;
};

type FinanceListStateKey =
  | "investmentRecords"
  | "savingsRecords"
  | "pensionRecords"
  | "accountRecords"
  | "liabilityRecords"
  | "allocationRecords";

export function financeRecordsPutMutationOptions(
  qc: QueryClient,
  spec: {
    readonly path: string;
    readonly listKey: FinanceListStateKey;
    readonly normalize: (raw: unknown) => FinancePersistedState[FinanceListStateKey];
  },
): UseMutationOptions<
  { records: FinancePersistedState[FinanceListStateKey] },
  Error,
  FinancePersistedState[FinanceListStateKey]
> {
  return {
    mutationFn: async (records) => {
      const res = await adminFetchJson<Record<string, unknown>>(spec.path, {
        method: "PUT",
        body: JSON.stringify({ [spec.listKey]: records }),
      });
      const list = res[spec.listKey];
      return { records: spec.normalize(list) };
    },
    onSuccess: ({ records }) => {
      qc.setQueryData<FinancePersistedState>(keys.finance, (old) => ({
        ...(old ?? DEFAULT_FINANCE_STATE),
        [spec.listKey]: records,
      }));
    },
  };
}

export function saveHouseMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({
      house,
      data,
    }: {
      house: HouseKey;
      data: HouseFinanceData;
    }) => {
      const res = await adminFetchJson<PutFinanceResponse>(`/finance/${house}`, {
        method: "PUT",
        body: JSON.stringify(data),
      });
      return { house, data: res.data };
    },
    onSuccess: ({ house, data }: { house: HouseKey; data: HouseFinanceData }) => {
      qc.setQueryData<FinancePersistedState>(keys.finance, (old) => ({
        ...(old ?? DEFAULT_FINANCE_STATE),
        [house]: data,
      }));
    },
  };
}

export function saveAllocationRecordsMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (records: readonly FinanceAllocationRecord[]) => {
      const res = await adminFetchJson<Record<string, unknown>>("/finance/allocations", {
        method: "PUT",
        body: JSON.stringify({
          allocationRecords: allocationRecordsToApiPayload(records),
        }),
      });
      const list = res.allocationRecords;
      return { records: normalizeAllocationRecords(list) };
    },
    onSuccess: ({ records }: { records: FinancePersistedState["allocationRecords"] }) => {
      qc.setQueryData<FinancePersistedState>(keys.finance, (old) => ({
        ...(old ?? DEFAULT_FINANCE_STATE),
        allocationRecords: records,
      }));
    },
  };
}

export function saveLedgerSheetMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({
      sheet,
      records,
      expenseAllocationPercents,
    }: {
      sheet: FinanceLedgerSheetKey;
      records: readonly FinanceLedgerRecord[];
      expenseAllocationPercents?: ExpenseIncomeAllocationPercents;
    }) => {
      const { path, bodyKey } = LEDGER_CONFIG[sheet];
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const bodyPayload: Record<string, unknown> = { [bodyKey]: records };
      if (sheet === "expenses") {
        bodyPayload.expenseIncomeAllocationPercents =
          expenseAllocationPercents ??
          state?.expenseIncomeAllocationPercents ??
          DEFAULT_EXPENSE_INCOME_ALLOCATION_PERCENTS;
      }
      const res = await adminFetchJson<
        Record<string, unknown> & { expenseIncomeAllocationPercents?: unknown }
      >(path, {
        method: "PUT",
        body: JSON.stringify(bodyPayload),
      });
      const list = res[bodyKey];
      const categories = sheet === "income" ? INCOME_CATEGORIES : EXPENSE_CATEGORIES;
      const normalizedRecords = normalizeLedgerRecords(list as unknown, categories, {
        includeIncomeFlags: sheet === "income",
        includeExpenseFlags: sheet === "expenses",
      });
      const nextPercents =
        sheet === "expenses" && res.expenseIncomeAllocationPercents !== undefined
          ? normalizeExpenseIncomeAllocationPercents(res.expenseIncomeAllocationPercents)
          : undefined;
      return {
        sheet,
        bodyKey,
        records: normalizedRecords,
        expenseIncomeAllocationPercents: nextPercents,
      };
    },
    onSuccess: async (payload: {
      sheet: FinanceLedgerSheetKey;
      bodyKey: keyof FinancePersistedState;
      records: readonly FinanceLedgerRecord[];
      expenseIncomeAllocationPercents?: ExpenseIncomeAllocationPercents;
    }) => {
      if (payload.sheet === "expenses") {
        const fresh = await fetchFinance();
        qc.setQueryData<FinancePersistedState>(keys.finance, fresh);
        return;
      }
      qc.setQueryData<FinancePersistedState>(keys.finance, (old) => ({
        ...(old ?? DEFAULT_FINANCE_STATE),
        [payload.bodyKey]: payload.records,
        ...(payload.expenseIncomeAllocationPercents !== undefined
          ? { expenseIncomeAllocationPercents: payload.expenseIncomeAllocationPercents }
          : {}),
      }));
    },
  };
}

export function useFinance() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: keys.finance,
    queryFn: fetchFinance,
  });

  const saveHouse = useMutation(saveHouseMutationOptions(qc));
  const saveInvestmentRecords = useMutation(
    financeRecordsPutMutationOptions(qc, {
      path: "/finance/investments",
      listKey: "investmentRecords",
      normalize: normalizeInvestmentRecords,
    }),
  );
  const saveSavingsRecords = useMutation(
    financeRecordsPutMutationOptions(qc, {
      path: "/finance/savings",
      listKey: "savingsRecords",
      normalize: normalizeSavingsRecords,
    }),
  );
  const savePensionRecords = useMutation(
    financeRecordsPutMutationOptions(qc, {
      path: "/finance/pension",
      listKey: "pensionRecords",
      normalize: normalizePensionRecords,
    }),
  );
  const saveAccountRecords = useMutation(
    financeRecordsPutMutationOptions(qc, {
      path: "/finance/accounts",
      listKey: "accountRecords",
      normalize: normalizeAccountRecords,
    }),
  );
  const saveLiabilityRecords = useMutation(
    financeRecordsPutMutationOptions(qc, {
      path: "/finance/liabilities",
      listKey: "liabilityRecords",
      normalize: normalizeLiabilityRecords,
    }),
  );
  const saveAllocationRecords = useMutation(saveAllocationRecordsMutationOptions(qc));
  const saveLedgerSheet = useMutation(saveLedgerSheetMutationOptions(qc));

  const patchHouse = useCallback(
    (house: HouseKey, patch: (prev: HouseFinanceData) => HouseFinanceData) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev = state?.[house] ?? DEFAULT_FINANCE_STATE[house];
      const next = patch(prev);
      saveHouse.mutate({ house, data: next });
    },
    [qc, saveHouse],
  );

  const patchInvestmentRecords = useCallback(
    (
      patch: (
        prev: readonly FinanceInvestmentRecord[],
      ) => readonly FinanceInvestmentRecord[],
    ) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev = state?.investmentRecords ?? DEFAULT_FINANCE_STATE.investmentRecords;
      const next = patch(prev);
      saveInvestmentRecords.mutate(next);
    },
    [qc, saveInvestmentRecords],
  );

  const patchSavingsRecords = useCallback(
    (patch: (prev: readonly FinanceSavingsRecord[]) => FinanceSavingsRecord[]) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev = state?.savingsRecords ?? DEFAULT_FINANCE_STATE.savingsRecords;
      const next = patch(prev);
      saveSavingsRecords.mutate(next);
    },
    [qc, saveSavingsRecords],
  );

  const patchPensionRecords = useCallback(
    (patch: (prev: readonly FinancePensionRecord[]) => FinancePensionRecord[]) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev = state?.pensionRecords ?? DEFAULT_FINANCE_STATE.pensionRecords;
      const next = patch(prev);
      savePensionRecords.mutate(next);
    },
    [qc, savePensionRecords],
  );

  const patchAccountRecords = useCallback(
    (patch: (prev: readonly FinanceAccountRecord[]) => FinanceAccountRecord[]) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev = state?.accountRecords ?? DEFAULT_FINANCE_STATE.accountRecords;
      const next = patch(prev);
      saveAccountRecords.mutate(next);
    },
    [qc, saveAccountRecords],
  );

  const patchLiabilityRecords = useCallback(
    (patch: (prev: readonly FinanceLiabilityRecord[]) => FinanceLiabilityRecord[]) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev = state?.liabilityRecords ?? DEFAULT_FINANCE_STATE.liabilityRecords;
      const next = patch(prev);
      saveLiabilityRecords.mutate(next);
    },
    [qc, saveLiabilityRecords],
  );

  const patchAllocationRecords = useCallback(
    (
      patch: (
        prev: readonly FinanceAllocationRecord[],
      ) => readonly FinanceAllocationRecord[],
    ) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev = state?.allocationRecords ?? DEFAULT_FINANCE_STATE.allocationRecords;
      const next = patch(prev);
      saveAllocationRecords.mutate([...next]);
    },
    [qc, saveAllocationRecords],
  );

  const patchLedgerRecords = useCallback(
    (
      sheet: FinanceLedgerSheetKey,
      patch: (prev: readonly FinanceLedgerRecord[]) => FinanceLedgerRecord[],
    ) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const prev =
        sheet === "income"
          ? (state?.incomeRecords ?? DEFAULT_FINANCE_STATE.incomeRecords)
          : (state?.expenseRecords ?? DEFAULT_FINANCE_STATE.expenseRecords);
      const next = patch(prev);
      const toSave =
        sheet === "income"
          ? next.filter((r) => r.isDerivedFromAllocation !== true)
          : next;
      saveLedgerSheet.mutate({ sheet, records: toSave });
    },
    [qc, saveLedgerSheet],
  );

  const patchExpenseIncomeAllocationPercents = useCallback(
    (next: ExpenseIncomeAllocationPercents) => {
      const state = qc.getQueryData<FinancePersistedState>(keys.finance);
      const records = state?.expenseRecords ?? DEFAULT_FINANCE_STATE.expenseRecords;
      saveLedgerSheet.mutate({
        sheet: "expenses",
        records,
        expenseAllocationPercents: next,
      });
    },
    [qc, saveLedgerSheet],
  );

  const ledgerSaveErr = saveLedgerSheet.error;
  const houseSaveErr = saveHouse.error;
  const investmentSaveErr = saveInvestmentRecords.error;
  const savingsSaveErr = saveSavingsRecords.error;
  const pensionSaveErr = savePensionRecords.error;
  const accountSaveErr = saveAccountRecords.error;
  const liabilitySaveErr = saveLiabilityRecords.error;
  const allocationSaveErr = saveAllocationRecords.error;
  const saveError =
    houseSaveErr ??
    ledgerSaveErr ??
    investmentSaveErr ??
    savingsSaveErr ??
    pensionSaveErr ??
    accountSaveErr ??
    liabilitySaveErr ??
    allocationSaveErr;

  return {
    data: q.data ?? DEFAULT_FINANCE_STATE,
    isLoading: q.isLoading,
    isError: q.isError,
    isRefetching: q.isRefetching,
    error: q.error,
    refetch: q.refetch,
    patchHouse,
    patchLedgerRecords,
    patchInvestmentRecords,
    patchSavingsRecords,
    patchPensionRecords,
    patchAccountRecords,
    patchLiabilityRecords,
    patchAllocationRecords,
    patchExpenseIncomeAllocationPercents,
    isSaving:
      saveHouse.isPending ||
      saveLedgerSheet.isPending ||
      saveInvestmentRecords.isPending ||
      saveSavingsRecords.isPending ||
      savePensionRecords.isPending ||
      saveAccountRecords.isPending ||
      saveLiabilityRecords.isPending ||
      saveAllocationRecords.isPending,
    saveError,
    saveErrorDetail: getAdminApiErrorMessage(saveError),
  };
}
