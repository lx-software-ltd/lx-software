import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardStaffPath,
  boardStaffTickPath,
  type BoardSeat,
  type BoardSeatOverride,
  type BoardStaffPayload,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_STAFF_KEY = [...BOARD_QUERY_KEY, "staff"] as const;

export function staffOverrideMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ seatId, override }: { seatId: string; override: BoardSeatOverride }) => {
      const res = await adminFetchJson<{ seat: BoardSeat }>(boardStaffPath(seatId), {
        method: "PUT",
        body: JSON.stringify(override),
      });
      return res.seat;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_STAFF_KEY });
    },
  };
}

export function staffResetMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (seatId: string) => {
      const res = await adminFetchJson<{ seat: BoardSeat }>(boardStaffPath(seatId), { method: "DELETE" });
      return res.seat;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_STAFF_KEY });
    },
  };
}

/** The tick runs in the background (202); refetch again once it has had time to move tasks. */
export const STAFF_TICK_REFETCH_DELAY_MS = 8000;

export function staffTickMutationOptions(qc: QueryClient) {
  const refetch = () => {
    void qc.invalidateQueries({ queryKey: BOARD_STAFF_KEY });
    void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
  };
  return {
    mutationFn: async () => {
      return adminFetchJson<{ ok?: boolean; queued?: boolean }>(boardStaffTickPath(), {
        method: "POST",
        body: JSON.stringify({}),
      });
    },
    onSuccess: () => {
      refetch();
      window.setTimeout(refetch, STAFF_TICK_REFETCH_DELAY_MS);
    },
  };
}

export function useBoardStaff() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: BOARD_STAFF_KEY,
    queryFn: () => adminFetchJson<BoardStaffPayload>(boardStaffPath()),
  });
  const override = useMutation(staffOverrideMutationOptions(qc));
  const reset = useMutation(staffResetMutationOptions(qc));
  const tick = useMutation(staffTickMutationOptions(qc));
  return {
    seats: query.data?.seats ?? [],
    counts: query.data?.counts ?? {},
    enabled: Boolean(query.data?.enabled),
    envEnabled: Boolean(query.data?.envEnabled),
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    override,
    reset,
    tick,
  };
}
