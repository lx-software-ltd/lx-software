import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function useMirroredBookSummary(bookKey: StatementBookKey) {
  const qc = useQueryClient();
  const path = statementBookApiPath(bookKey);
  const wasPending = useRef(false);
  const query = useQuery({
    queryKey: [bookKey, "summary"] as const,
    queryFn: async () => {
      const data = await adminFetchJson<MirroredBookSummary>(`${path}/summary`);
      if (wasPending.current && !mirroredSyncIsPending(data)) {
        wasPending.current = false;
        void qc.invalidateQueries({ queryKey: [bookKey] });
      }
      if (mirroredSyncIsPending(data)) {
        wasPending.current = true;
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
  const sync = useMutation({
    mutationFn: () =>
      adminFetchJson<MirroredBookSyncResponse>(`${path}/sync`, { method: "POST" }),
    onSuccess: (data) => {
      qc.setQueryData([bookKey, "summary"], data);
      if (data.queued && data.pendingSince) {
        wasPending.current = true;
        return;
      }
      void qc.invalidateQueries({ queryKey: [bookKey] });
    },
  });
  const isSyncing =
    sync.isPending || (mirroredSyncIsPending(query.data) && !mirroredSyncTimedOut(query.data));
  return { query, sync, isSyncing, waitTimedOut: mirroredSyncTimedOut(query.data) };
}
