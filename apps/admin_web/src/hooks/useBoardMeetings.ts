import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  BOARD_API_BASE,
  boardMeetingPath,
  type BoardMeetingDetail,
  type BoardMeetingMode,
  type BoardMeetingSummary,
  type BoardTurn,
} from "../lib/boardModel";
import { BOARD_MEETING_POLL_INTERVAL_MS } from "../lib/contracts/generated";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_MEETINGS_KEY = [...BOARD_QUERY_KEY, "meetings"] as const;

export type MeetingWithTurns = {
  readonly meeting: BoardMeetingDetail;
  readonly turns: readonly BoardTurn[];
};

export function useBoardMeetings(enabled = true) {
  return useQuery({
    queryKey: BOARD_MEETINGS_KEY,
    enabled,
    queryFn: async () => {
      const res = await adminFetchJson<{ meetings: BoardMeetingSummary[] }>(`${BOARD_API_BASE}/meetings`);
      return res.meetings;
    },
    refetchInterval: (query) =>
      query.state.data?.some((m) => m.status === "running") ? BOARD_MEETING_POLL_INTERVAL_MS : false,
  });
}

export function useBoardMeeting(meetingId: string | null) {
  const qc = useQueryClient();
  const key = [...BOARD_MEETINGS_KEY, meetingId ?? ""] as const;
  return useQuery({
    queryKey: key,
    enabled: Boolean(meetingId),
    queryFn: async () => {
      const wasRunning = qc.getQueryData<MeetingWithTurns>(key)?.meeting.status === "running";
      const next = await adminFetchJson<MeetingWithTurns>(boardMeetingPath(meetingId!));
      if (wasRunning && next.meeting.status !== "running") {
        // The meeting just finished: actions, history and header counts changed server-side.
        void qc.invalidateQueries({ queryKey: [...BOARD_QUERY_KEY, "actions"] });
        void qc.invalidateQueries({ queryKey: BOARD_MEETINGS_KEY, exact: true });
        void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY, exact: true });
      }
      return next;
    },
    refetchInterval: (query) =>
      query.state.data?.meeting.status === "running" ? BOARD_MEETING_POLL_INTERVAL_MS : false,
  });
}

export type StartMeetingVariables = {
  readonly mode: BoardMeetingMode;
  readonly chair?: string;
  readonly topic?: string;
};

export function useStartBoardMeeting() {
  const qc = useQueryClient();
  return useMutation<BoardMeetingSummary, Error, StartMeetingVariables>({
    mutationFn: async (vars) => {
      const res = await adminFetchJson<{ meetingId: string; meeting: BoardMeetingSummary }>(
        `${BOARD_API_BASE}/meetings`,
        { method: "POST", body: JSON.stringify(vars) },
      );
      return res.meeting;
    },
    onSuccess: () => {
      // A meeting may already be finished by the time the start call returns
      // (fast runs, or inline execution without async self-invocation), so
      // refresh every board query, including the actions list.
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  });
}

export function useCancelBoardMeeting() {
  const qc = useQueryClient();
  return useMutation<BoardMeetingSummary, Error, string>({
    mutationFn: async (meetingId) => {
      const res = await adminFetchJson<{ meeting: BoardMeetingSummary }>(
        `${boardMeetingPath(meetingId)}/cancel`,
        { method: "POST" },
      );
      return res.meeting;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_MEETINGS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY, exact: true });
    },
  });
}
