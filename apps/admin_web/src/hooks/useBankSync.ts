import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import { keys } from "../lib/queryKeys";
import {
  BANKING_CALLBACK_PATH,
  type BankOption,
  type BankSyncMapping,
  type BankSyncReport,
  type BankSyncSession,
  type BankSyncState,
} from "../lib/bankSyncModel";

const BANKING_QUERY_KEY = keys.banking;

function invalidateBanking(qc: QueryClient): void {
  void qc.invalidateQueries({ queryKey: BANKING_QUERY_KEY });
}

export function startBankAuthMutationOptions() {
  return {
    mutationFn: (vars: { readonly bankName: string; readonly country: string }) =>
      adminFetchJson<{ url: string; state: string }>("/banking/auth", {
        method: "POST",
        body: JSON.stringify({
          ...vars,
          redirectUrl: `${window.location.origin}${BANKING_CALLBACK_PATH}`,
        }),
      }),
  };
}

export function completeBankAuthMutationOptions(qc: QueryClient) {
  return {
    mutationFn: (vars: { readonly code: string; readonly state: string }) =>
      adminFetchJson<{ session: BankSyncSession }>("/banking/sessions", {
        method: "POST",
        body: JSON.stringify(vars),
      }),
    onSuccess: () => invalidateBanking(qc),
  };
}

export function saveBankMappingsMutationOptions(qc: QueryClient) {
  return {
    mutationFn: (mappings: readonly BankSyncMapping[]) =>
      adminFetchJson<{ mappings: readonly BankSyncMapping[] }>("/banking/mappings", {
        method: "PUT",
        body: JSON.stringify({ mappings }),
      }),
    onSuccess: () => invalidateBanking(qc),
  };
}

export function syncBankNowMutationOptions(qc: QueryClient) {
  return {
    mutationFn: () =>
      adminFetchJson<BankSyncReport>("/banking/sync", {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: () => {
      invalidateBanking(qc);
      void qc.invalidateQueries({ queryKey: keys.finance });
    },
  };
}

export function deleteBankSessionMutationOptions(qc: QueryClient) {
  return {
    mutationFn: (sessionId: string) =>
      adminFetchJson<{ sessions: readonly BankSyncSession[] }>(
        `/banking/sessions/${encodeURIComponent(sessionId)}`,
        { method: "DELETE" },
      ),
    onSuccess: () => invalidateBanking(qc),
  };
}

export function useBankSync() {
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: BANKING_QUERY_KEY,
    queryFn: () => adminFetchJson<BankSyncState>("/banking"),
  });

  const startAuth = useMutation(startBankAuthMutationOptions());
  const completeAuth = useMutation(completeBankAuthMutationOptions(qc));
  const saveMappings = useMutation(saveBankMappingsMutationOptions(qc));
  const syncNow = useMutation(syncBankNowMutationOptions(qc));
  const deleteSession = useMutation(deleteBankSessionMutationOptions(qc));

  return {
    state: q.data,
    isLoading: q.isLoading,
    isError: q.isError,
    isRefetching: q.isRefetching,
    error: q.error,
    refetch: q.refetch,
    startAuth,
    completeAuth,
    saveMappings,
    syncNow,
    deleteSession,
  };
}

export function useBankOptions(country: string) {
  return useQuery({
    queryKey: [...keys.banking, "banks", country],
    queryFn: () =>
      adminFetchJson<{ banks: readonly BankOption[] }>(
        `/banking/banks?country=${encodeURIComponent(country)}`,
      ),
    enabled: country.length === 2,
    staleTime: 10 * 60 * 1000,
  });
}
