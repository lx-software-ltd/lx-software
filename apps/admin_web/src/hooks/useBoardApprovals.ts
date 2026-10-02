import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import { BOARD_API_BASE, boardApprovalDecisionPath, type BoardApproval } from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_ACTIONS_KEY } from "./useBoardActions";
import { BOARD_TOOL_CALLS_KEY } from "./useBoardTools";

export const BOARD_APPROVALS_KEY = [...BOARD_QUERY_KEY, "approvals"] as const;

export type ApprovalDecisionVariables = {
  readonly approvalId: string;
  readonly decision: "approve" | "reject";
  readonly note?: string;
  /** Owner-edited arguments; only honoured on approve. */
  readonly arguments?: Readonly<Record<string, unknown>>;
};

/**
 * Mutation options for approving / rejecting a queued tool call, kept apart
 * from the hook so the request body and cache invalidation are unit-testable
 * without rendering React.
 */
export function approvalDecisionMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ approvalId, decision, note, arguments: args }: ApprovalDecisionVariables) => {
      const res = await adminFetchJson<{ approval: BoardApproval }>(boardApprovalDecisionPath(approvalId, decision), {
        method: "POST",
        body: JSON.stringify({ note: note ?? "", ...(args && decision === "approve" ? { arguments: args } : {}) }),
      });
      return res.approval;
    },
    onSuccess: (approval: BoardApproval, variables: ApprovalDecisionVariables) => {
      qc.setQueryData<BoardApproval[]>(BOARD_APPROVALS_KEY, (prev) =>
        (prev ?? []).map((a) => (a.approvalId === approval.approvalId ? approval : a)),
      );
      if (variables.decision === "approve" || approval.status === "executed") {
        // An approved write may have sent mail, raised an invoice, replied on
        // Meta or added an action: refresh every board query (the root prefix
        // covers the overview, approvals, tool calls, mail, receivables, meta
        // threads and actions) so the executed result shows without a reload.
        void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
        return;
      }
      void qc.invalidateQueries({ queryKey: BOARD_APPROVALS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY, exact: true });
      void qc.invalidateQueries({ queryKey: BOARD_TOOL_CALLS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_ACTIONS_KEY });
    },
  };
}

export function useBoardApprovals(enabled = true) {
  const qc = useQueryClient();

  const query = useQuery({
    queryKey: BOARD_APPROVALS_KEY,
    enabled,
    queryFn: async () => {
      const res = await adminFetchJson<{ approvals: BoardApproval[] }>(`${BOARD_API_BASE}/approvals`);
      return res.approvals;
    },
  });

  const decide = useMutation<BoardApproval, Error, ApprovalDecisionVariables>(approvalDecisionMutationOptions(qc));

  return {
    approvals: query.data ?? [],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    decide,
  };
}
