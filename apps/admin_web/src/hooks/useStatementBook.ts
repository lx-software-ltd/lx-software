import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { keys } from "../lib/queryKeys";
import { adminFetchJson, getAdminApiErrorMessage } from "../lib/apiAdminClient";
import { GLOBAL_DEFAULT_CURRENCY } from "../lib/currencies";
import type { StatementBookKey } from "../lib/financeTypes";
import {
  normalizeHouseFinanceData,
  type HouseFinanceData,
} from "../lib/financeModel";
import { statementBookApiPath } from "../lib/statementOwners";

export const EMPTY_STATEMENT_BOOK: HouseFinanceData = {
  defaultCurrency: GLOBAL_DEFAULT_CURRENCY,
  float: { amount: 0, currency: GLOBAL_DEFAULT_CURRENCY },
  lines: [],
};

type PutBookResponse = {
  readonly data: HouseFinanceData;
};

export function saveStatementBookMutationOptions(qc: QueryClient, bookKey: StatementBookKey) {
  const apiPath = statementBookApiPath(bookKey);
  return {
    mutationFn: async (data: HouseFinanceData) => {
      const res = await adminFetchJson<PutBookResponse>(apiPath, {
        method: "PUT",
        body: JSON.stringify({
          ...data,
          defaultCurrency: GLOBAL_DEFAULT_CURRENCY,
          float: data.float ?? { amount: 0, currency: GLOBAL_DEFAULT_CURRENCY },
        }),
      });
      return normalizeHouseFinanceData(res.data);
    },
    onSuccess: (data: HouseFinanceData) => {
      qc.setQueryData<HouseFinanceData>(keys.book(bookKey), data);
    },
  };
}

export function statementBookQuery(bookKey: StatementBookKey) {
  return {
    queryKey: keys.book(bookKey),
    queryFn: async (): Promise<HouseFinanceData> => {
      const raw = await adminFetchJson<PutBookResponse>(statementBookApiPath(bookKey));
      return normalizeHouseFinanceData(raw.data);
    },
  };
}

export function useStatementBook(bookKey: StatementBookKey) {
  const qc = useQueryClient();

  const q = useQuery(statementBookQuery(bookKey));

  const saveBook = useMutation(saveStatementBookMutationOptions(qc, bookKey));

  const patchBook = useCallback(
    (patch: (prev: HouseFinanceData) => HouseFinanceData) => {
      const prev = qc.getQueryData<HouseFinanceData>(keys.book(bookKey)) ?? EMPTY_STATEMENT_BOOK;
      saveBook.mutate(patch(prev));
    },
    [bookKey, qc, saveBook],
  );

  return {
    data: q.data ?? EMPTY_STATEMENT_BOOK,
    isLoading: q.isLoading,
    isError: q.isError,
    isRefetching: q.isRefetching,
    error: q.error,
    refetch: q.refetch,
    patchBook,
    isSaving: saveBook.isPending,
    saveError: saveBook.error,
    saveErrorDetail: getAdminApiErrorMessage(saveBook.error),
  };
}
