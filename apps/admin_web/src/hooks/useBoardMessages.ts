import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  BOARD_API_BASE,
  boardMessagesPath,
  boardMessagesStatusPath,
  boardMessageThreadPath,
} from "../lib/boardModel";
import { BOARD_QUERY_KEY } from "./useBoard";

export const BOARD_MESSAGES_KEY = [...BOARD_QUERY_KEY, "messages"] as const;

export type BoardMessageThread = {
  readonly threadId: string;
  readonly channel: string;
  readonly displayName: string;
  readonly phone: string;
  readonly lastText: string;
  readonly lastDirection: string;
  readonly lastMessageAt: string;
  readonly unread: boolean;
  readonly messageCount: number;
  readonly prospectId: string;
};

export type BoardMessage = {
  readonly messageId: string;
  readonly receivedAt: string;
  readonly direction: string;
  readonly text: string;
  readonly senderName: string;
  readonly attachments: readonly { readonly kind: string; readonly name?: string; readonly stored?: boolean; readonly key?: string }[];
};

export type BoardMessageStatus = {
  readonly configured: boolean;
  readonly pageSet: boolean;
  readonly whatsappSet: boolean;
  readonly unreadCount: number;
  readonly lastDelivery: { readonly page?: string; readonly instagram?: string; readonly whatsapp?: string };
  readonly whatsapp: {
    readonly connected: boolean;
    readonly phoneNumberId: string;
    readonly wabaId: string;
    readonly historyDeclined: boolean;
    readonly disconnectedAt: string;
    readonly sync: { readonly startedAt?: string };
  };
};

export function useBoardMessages(channel: string) {
  return useQuery({
    queryKey: [...BOARD_MESSAGES_KEY, "list", channel],
    queryFn: () => adminFetchJson<{ threads: BoardMessageThread[]; count: number }>(boardMessagesPath(channel)),
    refetchInterval: 60_000,
  });
}

export function useBoardMessageThread(threadId: string | null) {
  return useQuery({
    queryKey: [...BOARD_MESSAGES_KEY, "thread", threadId ?? ""],
    enabled: !!threadId,
    queryFn: () => adminFetchJson<{ thread: BoardMessageThread; messages: BoardMessage[] }>(boardMessageThreadPath(threadId ?? "")),
  });
}

export function useBoardMessageStatus() {
  return useQuery({
    queryKey: [...BOARD_MESSAGES_KEY, "status"],
    queryFn: () => adminFetchJson<BoardMessageStatus>(boardMessagesStatusPath()),
  });
}

export function useBoardMessageRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (threadId: string) =>
      adminFetchJson<{ thread: BoardMessageThread }>(`${boardMessageThreadPath(threadId)}/read`, { method: "POST", body: "{}" }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: BOARD_MESSAGES_KEY });
      void qc.invalidateQueries({ queryKey: BOARD_QUERY_KEY });
    },
  });
}

export function useBoardWhatsAppConnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { wabaId: string; phoneNumberId: string }) =>
      adminFetchJson<BoardMessageStatus["whatsapp"]>(`${BOARD_API_BASE}/messages/whatsapp/connect`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSettled: () => void qc.invalidateQueries({ queryKey: BOARD_MESSAGES_KEY }),
  });
}

export function useBoardWhatsAppSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => adminFetchJson<{ ok: boolean }>(`${BOARD_API_BASE}/messages/whatsapp/sync`, { method: "POST", body: "{}" }),
    onSettled: () => void qc.invalidateQueries({ queryKey: BOARD_MESSAGES_KEY }),
  });
}
