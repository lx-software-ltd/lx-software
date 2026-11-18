import type { MockCtx } from "./types";
import { json } from "./context";

type Thread = {
  threadId: string;
  channel: string;
  displayName: string;
  phone: string;
  lastText: string;
  lastDirection: string;
  lastMessageAt: string;
  unread: boolean;
  messageCount: number;
  prospectId: string;
};

const threads: Thread[] = [
  {
    threadId: "thread-harbour",
    channel: "whatsapp",
    displayName: "Harbour Club",
    phone: "85290001111",
    lastText: "Saturday 9am at the court",
    lastDirection: "in",
    lastMessageAt: "2026-11-18T08:00:00.000Z",
    unread: true,
    messageCount: 2,
    prospectId: "org-harbour",
  },
];

const messages = [
  {
    messageId: "m-out",
    receivedAt: "2026-11-16T02:00:00.000Z",
    direction: "out",
    text: "Hi Harbour Club, could you send the latest schedule?",
    senderName: "",
    attachments: [],
  },
  {
    messageId: "m-in",
    receivedAt: "2026-11-18T08:00:00.000Z",
    direction: "in",
    text: "Saturday 9am at the court",
    senderName: "Harbour Club",
    attachments: [],
  },
];

let whatsapp = {
  connected: false,
  phoneNumberId: "",
  wabaId: "",
  historyDeclined: false,
  disconnectedAt: "",
  sync: {} as { startedAt?: string },
};

export function handleMessages(ctx: MockCtx): Response | null {
  const path = ctx.path;
  const prefix = "/siu-tin-dei/board/messages";
  if (!path.startsWith(prefix)) return null;
  if (path === prefix && ctx.method === "GET") {
    const channel = ctx.url.searchParams.get("channel") || "all";
    const shown = threads.filter((thread) => channel === "all" || thread.channel === channel);
    return json({ threads: shown, count: shown.length, unreadCount: shown.filter((thread) => thread.unread).length });
  }
  if (path === `${prefix}/status` && ctx.method === "GET") {
    return json({
      configured: true,
      pageSet: true,
      whatsappSet: whatsapp.connected,
      unreadCount: threads.filter((thread) => thread.unread).length,
      lastDelivery: { page: "", instagram: "", whatsapp: "" },
      whatsapp,
    });
  }
  if (path === `${prefix}/whatsapp/connect` && ctx.method === "POST") {
    const body = JSON.parse(String(ctx.init.body || "{}")) as { wabaId?: string; phoneNumberId?: string };
    whatsapp = { ...whatsapp, connected: true, wabaId: body.wabaId || "", phoneNumberId: body.phoneNumberId || "" };
    return json({ ok: true, ...whatsapp });
  }
  if (path === `${prefix}/whatsapp/sync` && ctx.method === "POST") {
    if (whatsapp.sync.startedAt) return json({ message: "WhatsApp history sync already ran for this connection" }, 400);
    whatsapp = { ...whatsapp, sync: { startedAt: "2026-11-18T09:00:00.000Z" } };
    return json({ ok: true, ...whatsapp.sync });
  }
  const threadMatch = path.match(/^\/siu-tin-dei\/board\/messages\/([^/]+)$/);
  if (threadMatch && ctx.method === "GET") {
    const thread = threads.find((item) => item.threadId === decodeURIComponent(threadMatch[1]));
    if (!thread) return json({ message: "not found" }, 404);
    return json({ thread, messages });
  }
  const readMatch = path.match(/^\/siu-tin-dei\/board\/messages\/([^/]+)\/read$/);
  if (readMatch && ctx.method === "POST") {
    const thread = threads.find((item) => item.threadId === decodeURIComponent(readMatch[1]));
    if (!thread) return json({ message: "not found" }, 404);
    thread.unread = false;
    return json({ thread });
  }
  return null;
}
