import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  BOARD_API_BASE,
  boardMemberPath,
  type BoardBrief,
  type BoardCharter,
  type BoardMember,
  type BoardMemberOverride,
  type BoardOverview,
  type BoardRepoSnapshotMeta,
  type BoardSettings,
  type BoardUpdate,
} from "../lib/boardModel";

export const BOARD_QUERY_KEY = ["board"] as const;

export function useBoard() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });

  const overview = useQuery({
    queryKey: BOARD_QUERY_KEY,
    queryFn: async () => {
      const wasRunning = Boolean(qc.getQueryData<BoardOverview>(BOARD_QUERY_KEY)?.runningMeeting);
      const next = await adminFetchJson<BoardOverview>(BOARD_API_BASE);
      if (wasRunning && !next.runningMeeting) {
        // The overview is the one query that is always mounted on the tab, so it
        // is the reliable place to notice a meeting finishing and refresh the
        // actions list and meeting history regardless of which section is open.
        void qc.invalidateQueries({ queryKey: [...BOARD_QUERY_KEY, "actions"] });
        void qc.invalidateQueries({ queryKey: [...BOARD_QUERY_KEY, "meetings"] });
      }
      return next;
    },
    refetchInterval: (query) =>
      query.state.data?.runningMeeting ? 5000 : false,
  });

  const saveCharter = useMutation({
    mutationFn: async (charter: Pick<BoardCharter, "vision" | "mission">) => {
      const res = await adminFetchJson<{ charter: BoardCharter }>(`${BOARD_API_BASE}/charter`, {
        method: "PUT",
        body: JSON.stringify(charter),
      });
      return res.charter;
    },
    onSuccess: invalidate,
  });

  const saveMember = useMutation({
    mutationFn: async ({ personaId, override }: { personaId: string; override: BoardMemberOverride }) => {
      const res = await adminFetchJson<{ member: BoardMember }>(boardMemberPath(personaId), {
        method: "PUT",
        body: JSON.stringify(override),
      });
      return res.member;
    },
    onSuccess: invalidate,
  });

  const resetMember = useMutation({
    mutationFn: async (personaId: string) => {
      const res = await adminFetchJson<{ member: BoardMember }>(boardMemberPath(personaId), {
        method: "DELETE",
      });
      return res.member;
    },
    onSuccess: invalidate,
  });

  const saveBrief = useMutation({
    mutationFn: async (markdown: string) => {
      const res = await adminFetchJson<{ brief: BoardBrief }>(`${BOARD_API_BASE}/brief`, {
        method: "PUT",
        body: JSON.stringify({ markdown }),
      });
      return res.brief;
    },
    onSuccess: invalidate,
  });

  const saveSettings = useMutation({
    mutationFn: async (patch: Partial<BoardSettings>) => {
      const res = await adminFetchJson<{ settings: BoardSettings }>(`${BOARD_API_BASE}/settings`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      return res.settings;
    },
    onSuccess: (settings) => {
      qc.setQueryData<BoardOverview>(BOARD_QUERY_KEY, (prev) => (prev ? { ...prev, settings } : prev));
      invalidate();
    },
  });

  const postUpdate = useMutation({
    mutationFn: async (text: string) => {
      const res = await adminFetchJson<{ update: BoardUpdate }>(`${BOARD_API_BASE}/updates`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      return res.update;
    },
    onSuccess: () => {
      void invalidate();
      void qc.invalidateQueries({ queryKey: [...BOARD_QUERY_KEY, "updates"] });
    },
  });

  const refreshRepoSnapshot = useMutation({
    mutationFn: async () => {
      const res = await adminFetchJson<{ repoSnapshot: BoardRepoSnapshotMeta }>(
        `${BOARD_API_BASE}/repo-snapshot/refresh`,
        { method: "POST" },
      );
      return res.repoSnapshot;
    },
    onSuccess: invalidate,
  });

  return {
    overview: overview.data,
    isLoading: overview.isLoading,
    isError: overview.isError,
    isRefetching: overview.isRefetching,
    error: overview.error,
    refetch: overview.refetch,
    saveCharter,
    saveMember,
    resetMember,
    saveBrief,
    saveSettings,
    postUpdate,
    refreshRepoSnapshot,
  };
}

export function useBoardUpdates() {
  return useQuery({
    queryKey: [...BOARD_QUERY_KEY, "updates"],
    queryFn: async () => {
      const res = await adminFetchJson<{ updates: BoardUpdate[] }>(`${BOARD_API_BASE}/updates`);
      return res.updates;
    },
  });
}
