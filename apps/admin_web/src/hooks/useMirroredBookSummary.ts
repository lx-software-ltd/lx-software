import { useRef } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { keys } from "../lib/queryKeys";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  mirroredSyncIsPending,
  mirroredSyncTimedOut,
  type MirroredBookSummary,
  type MirroredBookSyncResponse,
} from "../lib/mirroredBook";
import type { StatementBookKey } from "../lib/financeTypes";
import { statementBookApiPath } from "../lib/statementOwners";

const SYNC_POLL_MS = 2_000;

export function mirroredBookSyncMutationOptions(
  qc: QueryClient,
  bookKey: StatementBookKey,
  path: string,
) {
  return {
    mutationFn: () => adminFetchJson<MirroredBookSyncResponse>(`${path}/sync`, { method: "POST" }),
    onSuccess: (data: MirroredBookSyncResponse) => {
      qc.setQueryData([...keys.book(bookKey), "summary"], data);
      if (data.queued && data.pendingSince) return;
      void qc.invalidateQueries({ queryKey: keys.book(bookKey) });
    },
  };
}

export function useMirroredBookSummary(bookKey: StatementBookKey) {
  const qc = useQueryClient();
  const path = statementBookApiPath(bookKey);
  const wasPendingRef = useRef(false);
  const query = useQuery({
    queryKey: [...keys.book(bookKey), "summary"] as const,
    queryFn: async () => {
      const data = await adminFetchJson<MirroredBookSummary>(`${path}/summary`);
      if (wasPendingRef.current && !mirroredSyncIsPending(data)) {
        wasPendingRef.current = false;
        void qc.invalidateQueries({ queryKey: keys.book(bookKey) });
      }
      if (mirroredSyncIsPending(data)) {
        wasPendingRef.current = true;
      }
      return data;
    },
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!mirroredSyncIsPending(data) || mirroredSyncTimedOut(data)) {
        return false;
      }
      return SYNC_POLL_MS;
    },
  });
  const syncOptions = mirroredBookSyncMutationOptions(qc, bookKey, path);
  const sync = useMutation({
    ...syncOptions,
    onSuccess: (data) => {
      if (data.queued && data.pendingSince) wasPendingRef.current = true;
      syncOptions.onSuccess(data);
    },
  });
  const isSyncing =
    sync.isPending || (mirroredSyncIsPending(query.data) && !mirroredSyncTimedOut(query.data));
  return { query, sync, isSyncing, waitTimedOut: mirroredSyncTimedOut(query.data) };
}
