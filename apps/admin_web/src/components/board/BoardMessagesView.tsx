import { useState } from "react";
import { DateTimeDisplay } from "../ui";
import {
  useBoardMessageRead,
  useBoardMessages,
  useBoardMessageStatus,
  useBoardMessageThread,
  useBoardWhatsAppConnect,
  useBoardWhatsAppSync,
  type BoardMessage,
} from "../../hooks/useBoardMessages";

const CHANNELS = [
  { id: "all", label: "All" },
  { id: "whatsapp", label: "WhatsApp" },
  { id: "page", label: "Facebook" },
  { id: "instagram", label: "Instagram" },
] as const;

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
        <WhatsAppConnect errorText={errorText} />
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
                <span className="fw-semibold">{item.displayName || item.phone || item.channel}</span>
                <span className="small">{item.channel}</span>
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
              <MessageRow key={message.messageId} message={message} />
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

function MessageRow({ message }: { readonly message: BoardMessage }) {
  const outbound = message.direction === "out";
  return (
    <li className="list-group-item">
      <div className="d-flex justify-content-between small text-muted">
        <span>{outbound ? "Sent" : message.senderName || "Received"}</span>
        <DateTimeDisplay iso={message.receivedAt} />
      </div>
      <pre className="mb-0 mt-1 board-mail-body">{message.text || "(attachment)"}</pre>
      {message.attachments.length > 0 ? (
        <div className="small mt-1">{message.attachments.map((item) => item.kind).join(", ")}</div>
      ) : null}
    </li>
  );
}

function WhatsAppConnect({ errorText }: { readonly errorText: (err: unknown) => string | null }) {
  const status = useBoardMessageStatus();
  const connect = useBoardWhatsAppConnect();
  const sync = useBoardWhatsAppSync();
  const [wabaId, setWabaId] = useState("");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  const wa = status.data?.whatsapp;
  const started = Boolean(wa?.sync?.startedAt);

  return (
    <div className="border rounded p-3">
      <h3 className="h6">WhatsApp</h3>
      <p className="small text-muted mb-2">
        Paste the WhatsApp Business account id and the phone number id from the app. This subscribes the app.
        It does not register the number, so the phone app keeps working. History can be imported once, and only
        within 24 hours of connecting the number.
      </p>
      {wa?.connected ? (
        <p className="small mb-2">
          Connected to phone number id <code>{wa.phoneNumberId}</code>.
          {started ? " History import already started." : ""}
          {wa.historyDeclined ? " History sharing was declined on the phone." : ""}
          {wa.disconnectedAt ? " The phone disconnected this app." : ""}
        </p>
      ) : (
        <form
          className="row g-2 align-items-end"
          onSubmit={(event) => {
            event.preventDefault();
            connect.mutate({ wabaId: wabaId.trim(), phoneNumberId: phoneNumberId.trim() });
          }}
        >
          <div className="col-12 col-md-4">
            <label className="form-label small" htmlFor="wa-waba">
              Business account id
            </label>
            <input id="wa-waba" className="form-control form-control-sm" value={wabaId} onChange={(event) => setWabaId(event.target.value)} />
          </div>
          <div className="col-12 col-md-4">
            <label className="form-label small" htmlFor="wa-phone">
              Phone number id
            </label>
            <input
              id="wa-phone"
              className="form-control form-control-sm"
              value={phoneNumberId}
              onChange={(event) => setPhoneNumberId(event.target.value)}
            />
          </div>
          <div className="col-12 col-md-4">
            <button type="submit" className="btn btn-sm btn-primary" disabled={connect.isPending}>
              Connect
            </button>
          </div>
        </form>
      )}
      {wa?.connected && !started ? (
        <button type="button" className="btn btn-sm btn-outline-primary mt-2" disabled={sync.isPending} onClick={() => sync.mutate()}>
          Import history once
        </button>
      ) : null}
      {connect.error ? <p className="text-danger small mb-0 mt-2">{errorText(connect.error)}</p> : null}
      {sync.error ? <p className="text-danger small mb-0 mt-2">{errorText(sync.error)}</p> : null}
    </div>
  );
}
