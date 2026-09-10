import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardHoldVetoClassPath,
  boardHoldVetoPath,
  boardHoldsPath,
  type BoardHold,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_HOLDS_KEY = [...BOARD_QUERY_KEY, "holds"] as const;

export type HoldVetoVariables = {
  readonly holdId: string;
  readonly reason?: string;
};

export function holdVetoMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ holdId, reason }: HoldVetoVariables) => {
      const res = await adminFetchJson<{ hold: BoardHold }>(boardHoldVetoPath(holdId), {
        method: "POST",
        body: JSON.stringify({ reason: reason ?? "" }),
      });
      return res.hold;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_HOLDS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  };
}

export function holdVetoClassMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (classKey: string) => {
      const res = await adminFetchJson<{ holds: BoardHold[] }>(boardHoldVetoClassPath(), {
        method: "POST",
        body: JSON.stringify({ classKey }),
      });
      return res.holds;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_HOLDS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  };
}

export function useBoardHolds() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: BOARD_HOLDS_KEY,
    queryFn: async () => {
      const res = await adminFetchJson<{ holds: BoardHold[] }>(boardHoldsPath({ status: "scheduled" }));
      return res.holds;
    },
  });
  const veto = useMutation(holdVetoMutationOptions(qc));
  const vetoClass = useMutation(holdVetoClassMutationOptions(qc));
  return {
    holds: query.data ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    veto,
    vetoClass,
  };
}
