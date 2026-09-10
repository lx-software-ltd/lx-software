import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { AdminApiError, adminFetchJson } from "../lib/apiAdminClient";
import { boardBoundariesPath, type BoardBoundaries } from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export function boundariesSaveMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ boundaries, version }: { readonly boundaries: BoardBoundaries; readonly version?: number }) => {
      try {
        const res = await adminFetchJson<{ boundaries: BoardBoundaries; version?: number }>(boardBoundariesPath(), {
          method: "PUT",
          body: JSON.stringify({ ...boundaries, version }),
        });
        return res.boundaries;
      } catch (err) {
        if (err instanceof AdminApiError && err.status === 409) {
          void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
        }
        throw err;
      }
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  };
}

export function useBoardBoundaries() {
  const qc = useQueryClient();
  const save = useMutation(boundariesSaveMutationOptions(qc));
  return { save };
}
