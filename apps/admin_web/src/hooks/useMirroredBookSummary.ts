import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import type { MirroredBookSummary } from "../lib/mirroredBook";
import type { StatementBookKey } from "../lib/financeTypes";
import { statementBookApiPath } from "../lib/statementOwners";

export function useMirroredBookSummary(bookKey: StatementBookKey) {
  const qc = useQueryClient();
  const path = statementBookApiPath(bookKey);
  const query = useQuery({
    queryKey: [bookKey, "summary"] as const,
    queryFn: () => adminFetchJson<MirroredBookSummary>(`${path}/summary`),
  });
  const sync = useMutation({
    mutationFn: () =>
      adminFetchJson<MirroredBookSummary>(`${path}/sync`, { method: "POST" }),
    onSuccess: (data) => {
      qc.setQueryData([bookKey, "summary"], data);
      void qc.invalidateQueries({ queryKey: [bookKey] });
    },
  });
  return { query, sync };
}
