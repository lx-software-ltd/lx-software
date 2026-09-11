import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  BOARD_API_BASE,
  boardMailThreadPath,
  type BoardMailListPayload,
  type BoardMailMaskedMessage,
  type BoardMailSelfTestResult,
  type BoardMailThread,
  type BoardMailThreadPayload,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_MAIL_KEY = [...BOARD_QUERY_KEY, "mail"] as const;

export type MailListFilters = {
  readonly mailbox?: string;
  readonly query?: string;
  readonly unreadOnly?: boolean;
};

function listPath(filters: MailListFilters): string {
  const params = new URLSearchParams();
  if (filters.mailbox) params.set("mailbox", filters.mailbox);
  if (filters.query?.trim()) params.set("q", filters.query.trim());
  if (filters.unreadOnly) params.set("unread", "1");
  params.set("limit", "100");
  return `${BOARD_API_BASE}/mail?${params.toString()}`;
}

export function useBoardMailThreads(filters: MailListFilters, enabled = true) {
  return useQuery({
    queryKey: [...BOARD_MAIL_KEY, "list", filters.mailbox ?? "", filters.query?.trim() ?? "", !!filters.unreadOnly],
    enabled,
    queryFn: () => adminFetchJson<BoardMailListPayload>(listPath(filters)),
    refetchInterval: 60_000,
  });
}

export function useBoardMailThread(threadId: string | null) {
  return useQuery({
    queryKey: [...BOARD_MAIL_KEY, "thread", threadId ?? ""],
    enabled: !!threadId,
    queryFn: () => adminFetchJson<BoardMailThreadPayload>(boardMailThreadPath(threadId ?? "")),
  });
}

/** The pseudonymised view a board member gets through the mail tools. */
export function useBoardMailThreadMasked(threadId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: [...BOARD_MAIL_KEY, "thread-masked", threadId ?? ""],
    enabled: !!threadId && enabled,
    queryFn: () =>
      adminFetchJson<{ thread: unknown; messages: BoardMailMaskedMessage[] }>(
        `${boardMailThreadPath(threadId ?? "")}?view=board`,
      ),
  });
}

/** Owner-only: one test mail from hello@ to the signed-in address; surfaces the SES refusal verbatim. */
export function useBoardMailSelfTest() {
  const qc = useQueryClient();
  return useMutation<BoardMailSelfTestResult, Error, void>({
    mutationFn: () =>
      adminFetchJson<BoardMailSelfTestResult>(`${BOARD_API_BASE}/mail/selftest`, { method: "POST", body: "{}" }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: [...BOARD_MAIL_KEY, "list"] });
    },
  });
}

export function useBoardMailRead() {
  const qc = useQueryClient();
  return useMutation<BoardMailThread, Error, { readonly threadId: string; readonly read: boolean }>({
    mutationFn: async ({ threadId, read }) => {
      const res = await adminFetchJson<{ thread: BoardMailThread }>(`${boardMailThreadPath(threadId)}/read`, {
        method: "POST",
        body: JSON.stringify({ read }),
      });
      return res.thread;
    },
    onSuccess: (thread) => {
      qc.setQueriesData<BoardMailListPayload>({ queryKey: [...BOARD_MAIL_KEY, "list"] }, (prev) =>
        prev
          ? {
              ...prev,
              threads: prev.threads.map((t) => (t.threadId === thread.threadId ? { ...t, unread: thread.unread } : t)),
            }
          : prev,
      );
      qc.setQueryData<BoardMailThreadPayload>([...BOARD_MAIL_KEY, "thread", thread.threadId], (prev) =>
        prev ? { ...prev, thread: { ...prev.thread, unread: thread.unread } } : prev,
      );
      void qc.invalidateQueries({ queryKey: [...BOARD_MAIL_KEY, "list"] });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY, exact: true });
    },
  });
}
