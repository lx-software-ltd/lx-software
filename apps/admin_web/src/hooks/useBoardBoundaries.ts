import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import { boardBoundariesPath, type BoardBoundaries } from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export function boundariesSaveMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (boundaries: BoardBoundaries) => {
      const res = await adminFetchJson<{ boundaries: BoardBoundaries }>(boardBoundariesPath(), {
        method: "PUT",
        body: JSON.stringify(boundaries),
      });
      return res.boundaries;
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
