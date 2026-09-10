import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardOutreachStatsPath,
  boardProspectImportPath,
  boardProspectMergePath,
  boardProspectPath,
  boardProspectsPath,
  boardSequencePath,
  type BoardOutreachStats,
  type BoardProspect,
  type BoardProspectWrite,
  type BoardSequence,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_PROSPECTS_KEY = [...BOARD_QUERY_KEY, "prospects"] as const;
export const BOARD_OUTREACH_STATS_KEY = [...BOARD_QUERY_KEY, "outreach-stats"] as const;

export function prospectPutMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ prospectId, body }: { readonly prospectId: string; readonly body: BoardProspectWrite }) => {
      const res = await adminFetchJson<{ prospect: BoardProspect }>(boardProspectPath(prospectId), {
        method: "PUT",
        body: JSON.stringify(body),
      });
      return res.prospect;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_PROSPECTS_KEY });
    },
  };
}

export function prospectImportMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (csv: string) =>
      adminFetchJson<{ created: number; updated: number; errors: string[] }>(boardProspectImportPath(), {
        method: "POST",
        body: JSON.stringify({ csv }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_PROSPECTS_KEY });
    },
  };
}

export function prospectMergeMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ prospectId, into }: { readonly prospectId: string; readonly into: string }) => {
      const res = await adminFetchJson<{ prospect: BoardProspect }>(boardProspectMergePath(prospectId), {
        method: "POST",
        body: JSON.stringify({ into }),
      });
      return res.prospect;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_PROSPECTS_KEY });
    },
  };
}

export function sequencePutMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ type, body }: { readonly type: string; readonly body: BoardSequence }) => {
      const res = await adminFetchJson<{ sequence: BoardSequence }>(boardSequencePath(type), {
        method: "PUT",
        body: JSON.stringify(body),
      });
      return res.sequence;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_PROSPECTS_KEY });
    },
  };
}

export function useBoardPipeline() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: BOARD_PROSPECTS_KEY,
    queryFn: () =>
      adminFetchJson<{
        prospects: BoardProspect[];
        needsContact: BoardProspect[];
        stats: BoardOutreachStats;
      }>(boardProspectsPath()),
  });
  const stats = useQuery({
    queryKey: BOARD_OUTREACH_STATS_KEY,
    queryFn: () => adminFetchJson<BoardOutreachStats>(boardOutreachStatsPath(28)),
  });
  const update = useMutation(prospectPutMutationOptions(qc));
  const importCsv = useMutation(prospectImportMutationOptions(qc));
  const merge = useMutation(prospectMergeMutationOptions(qc));
  const saveSequence = useMutation(sequencePutMutationOptions(qc));
  return {
    prospects: list.data?.prospects ?? [],
    needsContact: list.data?.needsContact ?? [],
    stats: stats.data ?? list.data?.stats,
    isLoading: list.isLoading,
    isError: list.isError,
    error: list.error,
    update,
    importCsv,
    merge,
    saveSequence,
  };
}

export function useBoardSequence(type: string) {
  return useQuery({
    queryKey: [...BOARD_QUERY_KEY, "sequence", type],
    queryFn: async () => {
      const res = await adminFetchJson<{ sequence: BoardSequence }>(boardSequencePath(type));
      return res.sequence;
    },
    enabled: Boolean(type),
  });
}
