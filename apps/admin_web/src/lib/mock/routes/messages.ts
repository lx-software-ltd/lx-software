import type { MockCtx } from "./types";
import { json } from "./context";

type Thread = {
  threadId: string;
  channel: string;
  displayName: string;
  handle?: string;
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
    phone: "85255500100",
    lastText: "Saturday 9am at the court",
    lastDirection: "in",
    lastMessageAt: "2026-11-18T08:00:00.000Z",
    unread: true,
    messageCount: 2,
    prospectId: "org-harbour",
  },
  {
    threadId: "thread-tide",
    channel: "page",
    displayName: "Tide Pool Studio",
    phone: "",
    lastText: "Do you list holiday camps?",
    lastDirection: "in",
    lastMessageAt: "2026-11-17T03:00:00.000Z",
    unread: false,
    messageCount: 1,
    prospectId: "",
  },
];

const messagesByThread: Record<string, unknown[]> = {
  "thread-tide": [
    {
      messageId: "m-tide",
      receivedAt: "2026-11-17T03:00:00.000Z",
      direction: "in",
      text: "Do you list holiday camps?",
      senderName: "Tide Pool Studio",
      attachments: [],
    },
  ],
};

const MOCK_PHOTO_SVG =
  '<svg xmlns="http://www.w3.org/2000/svg" width="480" height="320"><rect width="480" height="320" fill="#dfe9f2"/><text x="240" y="165" font-family="sans-serif" font-size="22" text-anchor="middle" fill="#234">Mock timetable photo</text></svg>';

/** Stands in for the signed link. A browser will not open a `data:` link in a tab, and it will open a blob. */
function mockPhotoUrl(): string {
  return URL.createObjectURL(new Blob([MOCK_PHOTO_SVG], { type: "image/svg+xml" }));
}

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
    attachments: [
      { kind: "image", mime: "image/jpeg", name: "", stored: true, ref: "a1b2c3d4e5f60718-0" },
      { kind: "document", mime: "application/pdf", name: "timetable.pdf", stored: false, ref: "a1b2c3d4e5f60718-1" },
    ],
  },
];

let whatsapp = {
  connected: false,
  phoneNumberId: "",
  wabaId: "",
  displayPhoneNumber: "",
  verifiedName: "",
  onBusinessApp: null as boolean | null,
  historyDeclined: false,
  disconnectedAt: "",
  sync: { done: false } as { startedAt?: string; done: boolean; contacts?: { ok: boolean }; history?: { ok: boolean } },
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
      lastDelivery: { page: "2026-11-17T03:00:00.000Z", instagram: "", whatsapp: whatsapp.connected ? "2026-11-18T08:00:00.000Z" : "" },
      whatsapp,
    });
  }
  if (path === `${prefix}/whatsapp/connect` && ctx.method === "POST") {
    const body = JSON.parse(String(ctx.init.body || "{}")) as { wabaId?: string; phoneNumberId?: string };
    if (!/^\d+$/.test(body.wabaId || "") || !/^\d+$/.test(body.phoneNumberId || "")) {
      return json({ message: "phoneNumberId and wabaId are required" }, 400);
    }
    whatsapp = {
      ...whatsapp,
      connected: true,
      wabaId: body.wabaId || "",
      phoneNumberId: body.phoneNumberId || "",
      displayPhoneNumber: "+852 5550 0100",
      verifiedName: "Siu Tin Dei",
      onBusinessApp: true,
    };
    return json({ ok: true, ...whatsapp });
  }
  if (path === `${prefix}/whatsapp/sync` && ctx.method === "POST") {
    if (whatsapp.sync.done) return json({ message: "WhatsApp history sync already ran for this connection" }, 409);
    whatsapp = { ...whatsapp, sync: { startedAt: "2026-11-18T09:00:00.000Z", done: true, contacts: { ok: true }, history: { ok: true } } };
    return json({ ok: true, ...whatsapp.sync });
  }
  if (path === `${prefix}/connect/page` && ctx.method === "POST") {
    return json({ ok: true, fields: ["messages", "message_echoes", "messaging_postbacks", "message_reactions", "feed"] });
  }
  const mediaMatch = path.match(/^\/siu-tin-dei\/board\/messages\/([^/]+)\/media\/([^/]+)$/);
  if (mediaMatch && ctx.method === "GET") {
    if (mediaMatch[2].endsWith("-0")) return json({ url: mockPhotoUrl(), kind: "image", mime: "image/svg+xml", name: "" });
    return json({ message: "This file is no longer available from Meta." }, 404);
  }
  const threadMatch = path.match(/^\/siu-tin-dei\/board\/messages\/([^/]+)$/);
  if (threadMatch && ctx.method === "GET") {
    const thread = threads.find((item) => item.threadId === decodeURIComponent(threadMatch[1]));
    if (!thread) return json({ message: "not found" }, 404);
    return json({ thread, messages: messagesByThread[thread.threadId] ?? messages });
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
