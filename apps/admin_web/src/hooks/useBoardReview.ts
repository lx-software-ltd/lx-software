import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  boardBreakerResetPath,
  boardBreakersPath,
  boardLessonConfirmPath,
  boardLessonDismissPath,
  boardLessonsPath,
  boardRampPath,
  boardRampPromotePath,
  boardCodePromotePath,
  boardCodeStagingPath,
  boardReviewPath,
  boardReviewWrongPath,
  type BoardBreaker,
  type BoardLesson,
  type BoardRampRow,
  type BoardReviewSnapshot,
  type BoardStagingPreview,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";
import { BOARD_HOLDS_KEY } from "./useBoardHolds";

export const BOARD_REVIEW_KEY = [...BOARD_QUERY_KEY, "review"] as const;
export const BOARD_LESSONS_KEY = [...BOARD_QUERY_KEY, "lessons"] as const;
export const BOARD_BREAKERS_KEY = [...BOARD_QUERY_KEY, "breakers"] as const;
export const BOARD_RAMP_KEY = [...BOARD_QUERY_KEY, "ramp"] as const;
export const BOARD_STAGING_KEY = [...BOARD_QUERY_KEY, "staging"] as const;

export function reviewWrongMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ callId, note }: { readonly callId: string; readonly note: string }) => {
      const res = await adminFetchJson<{ lesson: BoardLesson }>(boardReviewWrongPath(callId), {
        method: "POST",
        body: JSON.stringify({ note }),
      });
      return res.lesson;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_LESSONS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_REVIEW_KEY });
    },
  };
}

export function lessonConfirmMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async ({ lessonId, instruction }: { readonly lessonId: string; readonly instruction?: string }) => {
      const res = await adminFetchJson<{ lesson: BoardLesson }>(boardLessonConfirmPath(lessonId), {
        method: "POST",
        body: JSON.stringify(instruction ? { instruction } : {}),
      });
      return res.lesson;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_LESSONS_KEY });
    },
  };
}

export function lessonDismissMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (lessonId: string) => {
      const res = await adminFetchJson<{ lesson: BoardLesson }>(boardLessonDismissPath(lessonId), {
        method: "POST",
        body: JSON.stringify({}),
      });
      return res.lesson;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_LESSONS_KEY });
    },
  };
}

export function breakerResetMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (name: string) => {
      const res = await adminFetchJson<{ breaker: BoardBreaker }>(boardBreakerResetPath(name), {
        method: "POST",
        body: JSON.stringify({}),
      });
      return res.breaker;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_BREAKERS_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_REVIEW_KEY });
    },
  };
}

export function stagingPromoteMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async () => {
      return adminFetchJson<{ approval: { readonly approvalId: string }; preview: BoardStagingPreview }>(
        boardCodePromotePath(),
        { method: "POST", body: JSON.stringify({}) },
      );
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_STAGING_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  };
}

export function rampPromoteMutationOptions(qc: QueryClient) {
  return {
    mutationFn: async (classKey: string) => {
      return adminFetchJson<{ classKey: string }>(boardRampPromotePath(classKey), {
        method: "POST",
        body: JSON.stringify({}),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: BOARD_RAMP_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_REVIEW_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_HOLDS_KEY });
    },
  };
}

export function useBoardReview(enabled: boolean) {
  const qc = useQueryClient();
  const review = useQuery({
    queryKey: BOARD_REVIEW_KEY,
    queryFn: async () => {
      const res = await adminFetchJson<{ review: BoardReviewSnapshot }>(boardReviewPath());
      return res.review;
    },
    enabled,
  });
  const lessons = useQuery({
    queryKey: BOARD_LESSONS_KEY,
    queryFn: async () => {
      const res = await adminFetchJson<{ lessons: BoardLesson[] }>(boardLessonsPath());
      return res.lessons;
    },
    enabled,
  });
  const breakers = useQuery({
    queryKey: BOARD_BREAKERS_KEY,
    queryFn: async () => {
      const res = await adminFetchJson<{ breakers: BoardBreaker[] }>(boardBreakersPath());
      return res.breakers;
    },
    enabled,
  });
  const ramp = useQuery({
    queryKey: BOARD_RAMP_KEY,
    queryFn: async () => {
      const res = await adminFetchJson<{ ramp: BoardRampRow[] }>(boardRampPath());
      return res.ramp;
    },
    enabled,
  });
  const staging = useQuery({
    queryKey: BOARD_STAGING_KEY,
    queryFn: async () => {
      const res = await adminFetchJson<{ staging: BoardStagingPreview }>(boardCodeStagingPath());
      return res.staging;
    },
    enabled,
  });
  return {
    review: review.data,
    lessons: lessons.data ?? [],
    breakers: breakers.data ?? [],
    ramp: ramp.data ?? [],
    staging: staging.data,
    isLoading: review.isLoading,
    isError: review.isError,
    error: review.error,
    markWrong: useMutation(reviewWrongMutationOptions(qc)),
    confirmLesson: useMutation(lessonConfirmMutationOptions(qc)),
    dismissLesson: useMutation(lessonDismissMutationOptions(qc)),
    resetBreaker: useMutation(breakerResetMutationOptions(qc)),
    promote: useMutation(rampPromoteMutationOptions(qc)),
    promoteStaging: useMutation(stagingPromoteMutationOptions(qc)),
  };
}
