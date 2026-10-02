import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  BOARD_API_BASE,
  boardActionPath,
  type BoardAction,
  type BoardActionStatus,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_ACTIONS_KEY = [...BOARD_QUERY_KEY, "actions"] as const;

export type UpdateActionVariables = {
  readonly actionId: string;
  readonly status?: BoardActionStatus;
  readonly note?: string;
};

export function useBoardActions(enabled = true) {
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: BOARD_ACTIONS_KEY,
    enabled,
    queryFn: async () => {
      const res = await adminFetchJson<{ actions: BoardAction[] }>(`${BOARD_API_BASE}/actions`);
      return res.actions;
    },
  });

  const update = useMutation<BoardAction, Error, UpdateActionVariables, { previous?: BoardAction[] }>({
    mutationFn: async ({ actionId, ...patch }) => {
      const res = await adminFetchJson<{ action: BoardAction }>(boardActionPath(actionId), {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      return res.action;
    },
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: BOARD_ACTIONS_KEY });
      const previous = qc.getQueryData<BoardAction[]>(BOARD_ACTIONS_KEY);
      qc.setQueryData<BoardAction[]>(BOARD_ACTIONS_KEY, (prev) =>
        (prev ?? []).map((a) =>
          a.actionId === vars.actionId
            ? { ...a, status: vars.status ?? a.status, note: vars.note ?? a.note }
            : a,
        ),
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) qc.setQueryData(BOARD_ACTIONS_KEY, context.previous);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: BOARD_ACTIONS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY, exact: true });
    },
  });

  return {
    actions: query.data ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    update,
  };
}
