import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardChangesPath,
  boardWatchPath,
  boardWatchlistPath,
  type BoardChangeNote,
  type BoardMarketBrief,
  type BoardWatch,
  type BoardWatchWrite,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_REVIEW_KEY } from "./useBoardReview";

export const BOARD_WATCHLIST_KEY = [...BOARD_QUERY_KEY, "watchlist"] as const;
export const BOARD_CHANGES_KEY = [...BOARD_QUERY_KEY, "changes"] as const;

export function watchAddMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (body: BoardWatchWrite) => {
      const res = await adminFetchJson<{ watch: BoardWatch }>(boardWatchlistPath(), {
        method: "POST",
        body: JSON.stringify(body),
      });
      return res.watch;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_WATCHLIST_KEY });
    },
  };
}

export function watchUpdateMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ watchId, body }: { readonly watchId: string; readonly body: BoardWatchWrite }) => {
      const res = await adminFetchJson<{ watch: BoardWatch }>(boardWatchPath(watchId), {
        method: "PUT",
        body: JSON.stringify(body),
      });
      return res.watch;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_WATCHLIST_KEY });
    },
  };
}

export function watchRemoveMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (watchId: string) => {
      await adminFetchJson<{ ok: boolean }>(boardWatchPath(watchId), { method: "DELETE" });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_WATCHLIST_KEY });
    },
  };
}

export function useBoardMarket() {
  const qc = useQueryClient();
  const watchlist = useQuery({
    queryKey: BOARD_WATCHLIST_KEY,
    queryFn: () =>
      adminFetchJson<{ watches: BoardWatch[]; latestBrief: BoardMarketBrief | null }>(boardWatchlistPath()),
  });
  const changes = useQuery({
    queryKey: BOARD_CHANGES_KEY,
    queryFn: async () => {
      const res = await adminFetchJson<{ changes: BoardChangeNote[] }>(boardChangesPath(7));
      return res.changes;
    },
  });
  const add = useMutation(watchAddMutationOptions(qc));
  const update = useMutation(watchUpdateMutationOptions(qc));
  const remove = useMutation(watchRemoveMutationOptions(qc));
  return {
    watches: watchlist.data?.watches ?? [],
    latestBrief: watchlist.data?.latestBrief ?? null,
    changes: changes.data ?? [],
    isLoading: watchlist.isLoading || changes.isLoading,
    isError: watchlist.isError || changes.isError,
    error: watchlist.error ?? changes.error,
    add,
    update,
    remove,
    invalidate: () => {
      void qc.invalidateQueries({ queryKey: BOARD_WATCHLIST_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_CHANGES_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_REVIEW_KEY });
    },
  };
}
