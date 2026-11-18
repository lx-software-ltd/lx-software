import { useState } from "react";
import { DateTimeDisplay } from "../ui";
import {
  fetchBoardMessageMediaUrl,
  useBoardMessageRead,
  useBoardMessages,
  useBoardMessageThread,
  type BoardMessage,
  type BoardMessageAttachment,
  type BoardMessageThread,
} from "../../hooks/useBoardMessages";
import { BoardMessagesConnections } from "./BoardMessagesConnections";

const CHANNELS = [
  { id: "all", label: "All" },
  { id: "whatsapp", label: "WhatsApp" },
  { id: "page", label: "Facebook" },
  { id: "instagram", label: "Instagram" },
] as const;

const CHANNEL_LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  page: "Facebook",
  instagram: "Instagram",
};

function channelLabel(channel: string): string {
  return CHANNEL_LABELS[channel] ?? channel;
}

function threadTitle(thread: BoardMessageThread): string {
  if (thread.displayName) return thread.displayName;
  if (thread.handle) return `@${thread.handle}`;
  if (thread.phone) return `+${thread.phone.replace(/^\+/, "")}`;
  return `${channelLabel(thread.channel)} contact`;
}

export function BoardMessagesView({ errorText }: { readonly errorText: (err: unknown) => string | null }) {
  const [channel, setChannel] = useState<(typeof CHANNELS)[number]["id"]>("all");
  const [activeId, setActiveId] = useState<string | null>(null);
  const list = useBoardMessages(channel);
  const thread = useBoardMessageThread(activeId);
  const markRead = useBoardMessageRead();
  const threads = list.data?.threads ?? [];

  return (
    <div className="row g-3">
      <div className="col-12">
        <BoardMessagesConnections errorText={errorText} />
      </div>
      <div className="col-12 col-lg-5">
        <div className="btn-group btn-group-sm mb-2" role="group" aria-label="Channel">
          {CHANNELS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`btn ${channel === item.id ? "btn-primary" : "btn-outline-secondary"}`}
              onClick={() => setChannel(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {list.isLoading ? <p className="text-muted">Loading messages…</p> : null}
        {list.error ? <p className="text-danger">{errorText(list.error)}</p> : null}
        {!list.isLoading && threads.length === 0 ? <p className="text-muted">No messages stored yet.</p> : null}
        <div className="list-group">
          {threads.map((item) => (
            <button
              key={item.threadId}
              type="button"
              className={`list-group-item list-group-item-action ${activeId === item.threadId ? "active" : ""}`}
              onClick={() => {
                setActiveId(item.threadId);
                if (item.unread) markRead.mutate(item.threadId);
              }}
            >
              <div className="d-flex justify-content-between gap-2">
                <span className="fw-semibold">{threadTitle(item)}</span>
                <span className="small">{channelLabel(item.channel)}</span>
              </div>
              <div className="small text-truncate">{item.lastText || "(no text)"}</div>
              {item.unread ? <span className="badge text-bg-primary">unread</span> : null}
            </button>
          ))}
        </div>
      </div>
      <div className="col-12 col-lg-7">
        {thread.data ? (
          <ul className="list-group">
            {thread.data.messages.map((message) => (
              <MessageRow key={message.messageId} message={message} threadId={thread.data.thread.threadId} errorText={errorText} />
            ))}
          </ul>
        ) : (
          <p className="text-muted">Choose a thread to read it.</p>
        )}
        {thread.error ? <p className="text-danger">{errorText(thread.error)}</p> : null}
      </div>
    </div>
  );
}

type RowProps = {
  readonly message: BoardMessage;
  readonly threadId: string;
  readonly errorText: (err: unknown) => string | null;
};

function MessageRow({ message, threadId, errorText }: RowProps) {
  const outbound = message.direction === "out";
  return (
    <li className="list-group-item">
      <div className="d-flex justify-content-between small text-muted">
        <span>{outbound ? "Sent" : message.senderName || "Received"}</span>
        <DateTimeDisplay iso={message.receivedAt} />
      </div>
      {message.text || message.attachments.length === 0 ? <pre className="mb-0 mt-1 board-mail-body">{message.text || "(no text)"}</pre> : null}
      {message.attachments.map((item, index) => (
        <AttachmentLink key={item.ref ?? index} attachment={item} threadId={threadId} errorText={errorText} />
      ))}
    </li>
  );
}

const ATTACHMENT_NOUNS: Record<string, string> = {
  image: "photo",
  sticker: "sticker",
  video: "video",
  audio: "voice message",
  document: "document",
};

function AttachmentLink({ attachment, threadId, errorText }: Omit<RowProps, "message"> & { readonly attachment: BoardMessageAttachment }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noun = ATTACHMENT_NOUNS[attachment.kind] ?? "file";
  // A photo's name is its caption, which the message text already shows.
  const named = noun === "document" || noun === "file" ? attachment.name : "";
  const label = named ? `Open ${noun}: ${named}` : `Open ${noun}`;
  const ref = attachment.ref;
  if (!ref) return <div className="small text-muted mt-1">{noun} (not available on this read)</div>;

  const open = async () => {
    // The tab is opened inside the click, before the request, so the browser does not block it.
    // The console's content policy only allows its own images, so the photo cannot be shown inline.
    const tab = window.open("about:blank", "_blank");
    setBusy(true);
    setError(null);
    try {
      const { url } = await fetchBoardMessageMediaUrl(threadId, ref);
      if (tab) {
        tab.opener = null;
        tab.location.href = url;
      } else {
        window.location.assign(url);
      }
    } catch (err) {
      tab?.close();
      setError(errorText(err) ?? "This file could not be opened.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-1">
      <button type="button" className="btn btn-link btn-sm p-0 align-baseline" disabled={busy} onClick={() => void open()}>
        {label}
      </button>
      {error ? <span className="text-danger small ms-2">{error}</span> : null}
    </div>
  );
}
