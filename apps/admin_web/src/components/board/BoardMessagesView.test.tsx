import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BoardMessageStatus } from "../../hooks/useBoardMessages";
import { BoardMessagesView } from "./BoardMessagesView";

const mocks = vi.hoisted(() => ({
  media: vi.fn(),
  read: vi.fn(),
  connect: vi.fn(),
  sync: vi.fn(),
  subscribe: vi.fn(),
  login: vi.fn(),
  whatsapp: {} as Record<string, unknown>,
}));

const idle = { isPending: false, isSuccess: false, error: null };

vi.mock("../../hooks/useBoardMessages", () => ({
  fetchBoardMessageMediaUrl: mocks.media,
  useBoardMessages: () => ({
    isLoading: false,
    error: null,
    data: {
      threads: [
        {
          threadId: "thread-1",
          channel: "whatsapp",
          displayName: "Harbour Club",
          phone: "85255500100",
          lastText: "Saturday 9am",
          lastDirection: "in",
          lastMessageAt: "2026-11-18T08:00:00.000Z",
          unread: true,
          messageCount: 1,
          prospectId: "",
        },
        {
          threadId: "thread-2",
          channel: "instagram",
          displayName: "",
          handle: "tidepool",
          phone: "",
          lastText: "Hello",
          lastDirection: "in",
          lastMessageAt: "2026-11-17T08:00:00.000Z",
          unread: false,
          messageCount: 1,
          prospectId: "",
        },
      ],
    },
  }),
  useBoardMessageThread: (threadId: string | null) => ({
    error: null,
    data: threadId
      ? {
          thread: { threadId },
          messages: [
            {
              messageId: "m-1",
              receivedAt: "2026-11-18T08:00:00.000Z",
              direction: "in",
              text: "",
              senderName: "Harbour Club",
              attachments: [
                { kind: "image", mime: "image/jpeg", stored: true, ref: "abc-0" },
                { kind: "document", mime: "application/pdf", name: "timetable.pdf", ref: "abc-1" },
              ],
            },
          ],
        }
      : undefined,
  }),
  useBoardMessageStatus: () => ({
    error: null,
    data: { configured: true, pageSet: true, whatsappSet: true, unreadCount: 1, lastDelivery: {}, whatsapp: mocks.whatsapp } as unknown as BoardMessageStatus,
  }),
  useBoardMessageRead: () => ({ ...idle, mutate: mocks.read }),
  useBoardWhatsAppConnect: () => ({ ...idle, mutate: mocks.connect }),
  useBoardWhatsAppSync: () => ({ ...idle, mutate: mocks.sync }),
  useBoardPageSubscribe: () => ({ ...idle, mutate: mocks.subscribe }),
}));

vi.mock("../../lib/board/metaSignup", () => ({
  loadFacebookSdk: () => Promise.resolve({ init: vi.fn(), login: mocks.login }),
  startWhatsAppSignup: () => Promise.resolve({ kind: "finished", wabaId: "111", phoneNumberId: "222" }),
}));

const stored = new Map<string, string>();

const connected = {
  connected: true,
  phoneNumberId: "222",
  wabaId: "111",
  displayPhoneNumber: "+852 5550 0100",
  verifiedName: "Example Listings",
  onBusinessApp: true,
  historyDeclined: false,
  disconnectedAt: "",
  sync: { done: false },
};

function renderView() {
  render(<BoardMessagesView errorText={(err) => (err instanceof Error ? err.message : null)} />);
}

describe("BoardMessagesView", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => {
      if (typeof mock === "function") mock.mockReset();
    });
    mocks.whatsapp = { ...connected };
    // Newer Node versions define their own localStorage, which hides jsdom's.
    stored.clear();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => void stored.set(key, value),
      },
    });
    // jsdom has no modal dialogs.
    HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
      this.open = false;
    };
  });

  it("opens a photo in a new tab through the media route", async () => {
    const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    mocks.media.mockResolvedValue({ url: "https://files.example.com/photo.jpg?sig=1" });
    renderView();

    fireEvent.click(screen.getByRole("button", { name: /Harbour Club/ }));
    expect(mocks.read).toHaveBeenCalledWith("thread-1");
    fireEvent.click(screen.getByRole("button", { name: "Open photo" }));

    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    await waitFor(() => expect(tab.location.href).toBe("https://files.example.com/photo.jpg?sig=1"));
    expect(mocks.media).toHaveBeenCalledWith("thread-1", "abc-0");
    expect(tab.opener).toBeNull();
    open.mockRestore();
  });

  it("closes the tab and says why when Meta no longer serves the file", async () => {
    const tab = { opener: null, location: { href: "" }, close: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    mocks.media.mockRejectedValue(new Error("This file is no longer available from Meta."));
    renderView();

    fireEvent.click(screen.getByRole("button", { name: /Harbour Club/ }));
    fireEvent.click(screen.getByRole("button", { name: "Open document: timetable.pdf" }));

    expect(await screen.findByText("This file is no longer available from Meta.")).toBeInTheDocument();
    expect(tab.close).toHaveBeenCalled();
    open.mockRestore();
  });

  it("names a thread that has no display name by its handle", () => {
    renderView();
    expect(screen.getByRole("button", { name: /@tidepool/ })).toHaveTextContent("Instagram");
  });

  it("asks before the one-time history import", () => {
    renderView();
    fireEvent.click(screen.getByRole("button", { name: "Import history" }));
    expect(mocks.sync).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("only within 24 hours of connecting");
    fireEvent.click(within(dialog).getByRole("button", { name: "Import history" }));
    expect(mocks.sync).toHaveBeenCalledTimes(1);
  });

  it("offers a retry when a step of the import failed, and nothing once it is done", () => {
    mocks.whatsapp = { ...connected, sync: { startedAt: "2026-11-18T09:00:00.000Z", done: false, history: { ok: false, error: "Meta refused the history request" } } };
    renderView();
    expect(screen.getByRole("button", { name: "Retry history import" })).toBeInTheDocument();
    expect(screen.getByText(/Meta refused the history request/)).toBeInTheDocument();
  });

  it("hides the import once Meta accepted it", () => {
    mocks.whatsapp = { ...connected, sync: { startedAt: "2026-11-18T09:00:00.000Z", done: true } };
    renderView();
    expect(screen.queryByRole("button", { name: /history import|Import history/ })).not.toBeInTheDocument();
    expect(screen.getByText(/History import requested/)).toBeInTheDocument();
  });

  it("warns when Meta says the number is not on the Business app", () => {
    mocks.whatsapp = { ...connected, onBusinessApp: false };
    renderView();
    expect(screen.getByText(/not linked to the WhatsApp Business app/)).toBeInTheDocument();
  });

  it("connects with the ids Meta's signup window reports", async () => {
    mocks.whatsapp = { ...connected, connected: false, displayPhoneNumber: "" };
    renderView();
    const button = screen.getByRole("button", { name: "Connect WhatsApp" });
    expect(button).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Meta app id"), { target: { value: "123456789" } });
    fireEvent.change(screen.getByLabelText("Signup configuration id"), { target: { value: "987654321" } });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    await waitFor(() => expect(mocks.connect).toHaveBeenCalledWith({ wabaId: "111", phoneNumberId: "222" }));
    expect(JSON.parse(stored.get("board.messages.metaSignup") ?? "{}")).toEqual({ appId: "123456789", configId: "987654321" });
  });

  it("subscribes the Page on request", () => {
    renderView();
    fireEvent.click(screen.getByRole("button", { name: "Subscribe Page" }));
    expect(mocks.subscribe).toHaveBeenCalledTimes(1);
  });
});
