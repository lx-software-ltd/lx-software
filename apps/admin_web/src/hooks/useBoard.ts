import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
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
import { BOARD_QUERY_KEY } from "../lib/queryKeys";

export { BOARD_QUERY_KEY };

function invalidateOverview(qc: QueryClient): void {
  void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY, exact: true });
}

export function saveCharterMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (charter: Pick<BoardCharter, "vision" | "mission">) => {
      const res = await adminFetchJson<{ charter: BoardCharter }>(`${BOARD_API_BASE}/charter`, {
        method: "PUT",
        body: JSON.stringify(charter),
      });
      return res.charter;
    },
    onSuccess: () => invalidateOverview(qc),
  };
}

export function saveMemberMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ personaId, override }: { personaId: string; override: BoardMemberOverride }) => {
      const res = await adminFetchJson<{ member: BoardMember }>(boardMemberPath(personaId), {
        method: "PUT",
        body: JSON.stringify(override),
      });
      return res.member;
    },
    onSuccess: () => invalidateOverview(qc),
  };
}

export function resetMemberMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (personaId: string) => {
      const res = await adminFetchJson<{ member: BoardMember }>(boardMemberPath(personaId), {
        method: "DELETE",
      });
      return res.member;
    },
    onSuccess: () => invalidateOverview(qc),
  };
}

export function saveBriefMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (markdown: string) => {
      const res = await adminFetchJson<{ brief: BoardBrief }>(`${BOARD_API_BASE}/brief`, {
        method: "PUT",
        body: JSON.stringify({ markdown }),
      });
      return res.brief;
    },
    onSuccess: () => invalidateOverview(qc),
  };
}

export function saveSettingsMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (patch: Partial<BoardSettings>) => {
      const res = await adminFetchJson<{ settings: BoardSettings }>(`${BOARD_API_BASE}/settings`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      return res.settings;
    },
    onSuccess: (settings: BoardSettings) => {
      qc.setQueryData<BoardOverview>(BOARD_QUERY_KEY, (prev) => (prev ? { ...prev, settings } : prev));
      // Settings feed tools, boundaries, review, holds, and staff. A prefix
      // invalidation refreshes those child queries. Charter and member saves
      // stay on the overview key only.
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  };
}

export function postUpdateMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (text: string) => {
      const res = await adminFetchJson<{ update: BoardUpdate }>(`${BOARD_API_BASE}/updates`, {
        method: "POST",
        body: JSON.stringify({ text }),
      });
      return res.update;
    },
    onSuccess: () => {
      invalidateOverview(qc);
      void qc.invalidateQueries({ queryKey: [...BOARD_QUERY_KEY, "updates"] });
    },
  };
}

export function refreshRepoSnapshotMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async () => {
      const res = await adminFetchJson<{ repoSnapshot: BoardRepoSnapshotMeta }>(
        `${BOARD_API_BASE}/repo-snapshot/refresh`,
        { method: "POST" },
      );
      return res.repoSnapshot;
    },
    onSuccess: () => invalidateOverview(qc),
  };
}

export function useBoard() {
  const qc = useQueryClient();

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
    refetchInterval: (query) => (query.state.data?.runningMeeting ? 5000 : false),
  });

  const saveCharter = useMutation(saveCharterMutationOptions(qc));
  const saveMember = useMutation(saveMemberMutationOptions(qc));
  const resetMember = useMutation(resetMemberMutationOptions(qc));
  const saveBrief = useMutation(saveBriefMutationOptions(qc));
  const saveSettings = useMutation(saveSettingsMutationOptions(qc));
  const postUpdate = useMutation(postUpdateMutationOptions(qc));
  const refreshRepoSnapshot = useMutation(refreshRepoSnapshotMutationOptions(qc));

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

export function useBoardUpdates(enabled = true) {
  return useQuery({
    queryKey: [...BOARD_QUERY_KEY, "updates"],
    enabled,
    queryFn: async () => {
      const res = await adminFetchJson<{ updates: BoardUpdate[] }>(`${BOARD_API_BASE}/updates`);
      return res.updates;
    },
  });
}
