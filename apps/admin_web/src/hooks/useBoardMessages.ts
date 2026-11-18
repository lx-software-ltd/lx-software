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
  /** Instagram username, when Meta returned one. */
  readonly handle?: string;
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
  readonly attachments: readonly BoardMessageAttachment[];
};

export type BoardMessageAttachment = {
  readonly kind: string;
  readonly name?: string;
  readonly mime?: string;
  readonly stored?: boolean;
  /** Handle for the media route. Absent on a read that may not open media. */
  readonly ref?: string;
};

export type BoardWhatsAppSyncStep = { readonly ok?: boolean; readonly error?: string };

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
    readonly displayPhoneNumber?: string;
    readonly verifiedName?: string;
    /** Meta's answer to "is this number also on the WhatsApp Business app". Null when Meta did not say. */
    readonly onBusinessApp?: boolean | null;
    readonly historyDeclined: boolean;
    readonly disconnectedAt: string;
    readonly sync: {
      readonly startedAt?: string;
      readonly done?: boolean;
      readonly contacts?: BoardWhatsAppSyncStep;
      readonly history?: BoardWhatsAppSyncStep;
    };
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
    refetchInterval: 60_000,
  });
}

/** The link is signed for a few minutes, so it is asked for when the owner opens the file. */
export function fetchBoardMessageMediaUrl(threadId: string, ref: string): Promise<{ url: string }> {
  return adminFetchJson<{ url: string }>(`${boardMessageThreadPath(threadId)}/media/${encodeURIComponent(ref)}`);
}

export function useBoardPageSubscribe() {
  return useMutation({
    mutationFn: () => adminFetchJson<{ ok: boolean; fields: string[] }>(`${BOARD_API_BASE}/messages/connect/page`, { method: "POST", body: "{}" }),
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
