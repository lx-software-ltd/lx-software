import { useEffect, useRef, useState } from "react";
import { DateTimeDisplay } from "../ui";
import {
  formatMailBytes,
  mailboxShortLabel,
  type BoardMailAttachment,
  type BoardMailListPayload,
  type BoardMailMaskedMessage,
  type BoardMailMessage,
  type BoardMailSendHealth,
  type BoardMailStatus,
  type BoardMailThread,
  type BoardMailThreadPayload,
} from "../../lib/boardModel";
import {
  useBoardMailRead,
  useBoardMailSelfTest,
  useBoardMailThread,
  useBoardMailThreadMasked,
  useBoardMailThreads,
} from "../../hooks/useBoardMail";

export type BoardMailViewProps = {
  readonly status: BoardMailStatus;
  /** Thread to open (from an approval preview's "open thread" link). */
  readonly focusThreadId?: string | null;
  readonly onFocusConsumed?: () => void;
  readonly errorText: (err: unknown) => string | null;
};

function senderLabel(thread: BoardMailThread): string {
  if (thread.lastDirection === "out") return `You → ${thread.participants[0] ?? ""}`;
  return thread.lastFromName ? `${thread.lastFromName} <${thread.lastFrom}>` : thread.lastFrom;
}

function AttachmentChips({ attachments }: { readonly attachments: readonly BoardMailAttachment[] }) {
  if (attachments.length === 0) return null;
  return (
    <div className="d-flex flex-wrap gap-2 mt-2">
      {attachments.map((a, idx) => (
        <span key={`${a.name}-${idx}`} className="badge text-bg-light border fw-normal" title={a.contentType}>
          <i className="bi bi-paperclip me-1" aria-hidden="true" />
          {a.name} <span className="text-muted">({formatMailBytes(a.size)})</span>
        </span>
      ))}
    </div>
  );
}

function MessageCard({
  message,
  masked,
}: {
  readonly message: BoardMailMessage | BoardMailMaskedMessage;
  readonly masked: boolean;
}) {
  const from = typeof message.from === "string" ? message.from : message.from.name ? `${message.from.name} <${message.from.address}>` : message.from.address;
  const isOut = message.direction === "out";
  return (
    <li className={`list-group-item board-mail-message ${isOut ? "board-mail-message-out" : "px-0"}`}>
      <div className="d-flex flex-wrap align-items-center gap-2 small">
        <span className={`badge ${isOut ? "text-bg-primary" : "text-bg-secondary"}`}>{isOut ? "sent" : "received"}</span>
        <span className="fw-semibold">{from}</span>
        <span className="text-muted">
          to {message.to.join(", ")}
          {message.cc.length > 0 ? `, cc ${message.cc.join(", ")}` : ""}
        </span>
        <span className="ms-auto text-muted">
          <DateTimeDisplay iso={message.date} />
        </span>
      </div>
      <pre className={`board-mail-body mt-2 mb-0 ${masked ? "board-mail-body-masked" : ""}`}>{message.text || "(no text body)"}</pre>
      <AttachmentChips attachments={message.attachments} />
    </li>
  );
}

function SetupHint({ status }: { readonly status: BoardMailStatus }) {
  return (
    <div className="alert alert-light border small mb-0">
      <div className="fw-semibold mb-1">
        <i className="bi bi-envelope-open me-1" aria-hidden="true" />
        No company email indexed yet
      </div>
      <p className="mb-1">
        Every message to any <code>@{status.domain}</code> mailbox is copied here once the Cloudflare Email Worker in{" "}
        <code>scripts/cloudflare/siutindei-mail-fanout.js</code> forwards to
        {status.inboundAddress ? <code className="ms-1">{status.inboundAddress}</code> : " the board's SES inbound address"}.
        Your own inbox keeps working exactly as before.
      </p>
      <p className="mb-0 text-muted">
        Board members read this index with contacts replaced by <code>contact#N</code> aliases; you always see the real
        addresses here. Setup steps: <code>docs/deployment/admin-website.md</code> → “Board mail”.
      </p>
    </div>
  );
}

function healthBadge(label: string, ok: boolean | null, detail?: string | null) {
  const cls = ok === null ? "text-bg-light border text-muted" : ok ? "text-bg-success" : "text-bg-danger";
  const icon = ok === null ? "bi-question-circle" : ok ? "bi-check-circle" : "bi-x-circle";
  return (
    <span className={`badge fw-normal ${cls}`} title={detail ?? undefined}>
      <i className={`bi ${icon} me-1`} aria-hidden="true" />
      {label}
      {detail ? <span className="ms-1 opacity-75">{detail}</span> : null}
    </span>
  );
}

/**
 * "sending on" used to mirror the stack flag alone, which stayed green while
 * SES refused every message. These badges come from SES itself, and the test
 * button sends one real message to the signed-in owner and shows the exact
 * refusal instead of spending a persona proposal plus an approval per attempt.
 */
function SendHealthStrip({
  status,
  health,
  errorText,
}: {
  readonly status: BoardMailStatus;
  readonly health: BoardMailSendHealth | undefined;
  readonly errorText: (err: unknown) => string | null;
}) {
  const selfTest = useBoardMailSelfTest();
  if (!status.sendEnabled) return null;
  const dkim = health?.dkimStatus ?? null;
  return (
    <div className="border rounded p-2 mb-3 small">
      <div className="d-flex flex-wrap align-items-center gap-2">
        <span className="text-muted">SES:</span>
        {healthBadge("domain verified", health ? health.identityVerified : null)}
        {healthBadge("DKIM", health ? (dkim === "SUCCESS" ? true : dkim ? false : null) : null, dkim)}
        {healthBadge(
          "production access",
          health ? health.productionAccess : null,
          health?.productionAccess === false ? "sandbox: only verified recipients" : null,
        )}
        {health?.dailyQuota ? (
          <span className="text-muted">
            {health.sentLast24h ?? 0}/{health.dailyQuota} sent today
          </span>
        ) : null}
        <button
          type="button"
          className="btn btn-sm btn-outline-primary ms-auto"
          disabled={selfTest.isPending}
          onClick={() => selfTest.mutate()}
          title={`Send one test message from hello@${status.domain} to your sign-in address`}
        >
          <i className="bi bi-send me-1" aria-hidden="true" />
          {selfTest.isPending ? "Sending…" : "Send test email"}
        </button>
      </div>
      {health?.errors.length ? (
        <ul className="mb-0 mt-2 text-danger">
          {health.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      ) : null}
      {selfTest.isSuccess ? (
        <div className="alert alert-success py-1 px-2 mt-2 mb-0">
          Sent to <code>{selfTest.data.to}</code> from <code>{selfTest.data.from}</code>
          {selfTest.data.sesMessageId ? (
            <span className="text-muted"> · SES id {selfTest.data.sesMessageId}</span>
          ) : null}
          . Check your inbox (and spam) in the next minute.
        </div>
      ) : null}
      {selfTest.isError ? (
        <div className="alert alert-danger py-1 px-2 mt-2 mb-0" style={{ overflowWrap: "anywhere" }}>
          {errorText(selfTest.error) ?? "The test message was refused."}
        </div>
      ) : null}
    </div>
  );
}

export function BoardMailView({ status, focusThreadId, onFocusConsumed, errorText }: BoardMailViewProps) {
  const [mailbox, setMailbox] = useState("");
  const [searchText, setSearchText] = useState("");
  const [query, setQuery] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showMasked, setShowMasked] = useState(false);

  const list = useBoardMailThreads({ mailbox, query, unreadOnly });
  const activeId = focusThreadId ?? selectedId;
  const thread = useBoardMailThread(activeId);
  const maskedThread = useBoardMailThreadMasked(activeId, showMasked);
  const markRead = useBoardMailRead();

  // Opening an unread thread marks it read once, like a mail client would.
  const autoReadFor = useRef<string | null>(null);
  useEffect(() => {
    const doc = thread.data;
    if (!doc || !doc.thread.unread || autoReadFor.current === doc.thread.threadId) return;
    autoReadFor.current = doc.thread.threadId;
    markRead.mutate({ threadId: doc.thread.threadId, read: true });
  }, [thread.data, markRead]);

  useEffect(() => {
    if (!searchText.trim() && !query) return;
    const handle = window.setTimeout(() => setQuery(searchText), 300);
    return () => window.clearTimeout(handle);
  }, [searchText, query]);

  const selectThread = (threadId: string) => {
    setSelectedId(threadId);
    if (focusThreadId) onFocusConsumed?.();
  };

  const payload: BoardMailListPayload | undefined = list.data;
  const threads = payload?.threads ?? [];
  const mailboxes = payload?.mailboxes ?? [];
  const totalIndexed = payload?.status.threadCount ?? status.threadCount;
  const health = payload?.status.sendHealth;
  const sendHealthy =
    !!health && health.identityVerified === true && health.productionAccess !== false && health.errors.length === 0;

  return (
    <div className="card shadow-sm mb-4">
      <div className="card-body">
        <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
          <h2 className="h6 text-uppercase text-muted mb-0">Company mail</h2>
          <div className="small text-muted">
            {totalIndexed} thread{totalIndexed === 1 ? "" : "s"} · {payload?.status.unreadCount ?? status.unreadCount} unread ·{" "}
            {status.sendEnabled ? (
              <span className={health ? (sendHealthy ? "text-success" : "text-danger") : "text-muted"}>
                <i className={`bi ${health && !sendHealthy ? "bi-send-exclamation" : "bi-send-check"} me-1`} aria-hidden="true" />
                {health ? (sendHealthy ? "sending on" : "sending not ready") : "sending enabled"}
              </span>
            ) : (
              <span>
                <i className="bi bi-send-slash me-1" aria-hidden="true" />
                sending off
              </span>
            )}
          </div>
        </div>
        <p className="text-muted small">
          Everything sent to <code>@{status.domain}</code>, as the board sees it — except that you see real names and
          addresses. Replies the board sends (or you approve) appear here as <span className="badge text-bg-primary">sent</span>.
        </p>
        <SendHealthStrip status={status} health={health} errorText={errorText} />
        {list.isError ? <div className="alert alert-danger py-2 small">{errorText(list.error)}</div> : null}
        {markRead.isError ? <div className="alert alert-danger py-2 small">{errorText(markRead.error)}</div> : null}

        {totalIndexed === 0 && !list.isLoading ? (
          <SetupHint status={status} />
        ) : (
          <div className="row g-3">
            <div className="col-12 col-lg-5 col-xl-4">
              <div className="d-flex flex-wrap gap-1 mb-2 board-mailbox-chips">
                <button
                  type="button"
                  className={`btn btn-sm ${mailbox === "" ? "btn-secondary" : "btn-outline-secondary"}`}
                  onClick={() => setMailbox("")}
                >
                  All
                </button>
                {mailboxes.map((m) => (
                  <button
                    key={m.address}
                    type="button"
                    className={`btn btn-sm ${mailbox === m.address ? "btn-secondary" : "btn-outline-secondary"}`}
                    title={m.address}
                    onClick={() => setMailbox(m.address)}
                  >
                    {mailboxShortLabel(m.address, status.domain)}
                    {m.unreadCount > 0 ? <span className="badge rounded-pill text-bg-warning ms-1">{m.unreadCount}</span> : null}
                  </button>
                ))}
              </div>
              <div className="input-group input-group-sm mb-2">
                <span className="input-group-text">
                  <i className="bi bi-search" aria-hidden="true" />
                </span>
                <input
                  className="form-control"
                  placeholder="Search subject, sender, snippet"
                  aria-label="Search mail"
                  value={searchText}
                  onChange={(ev) => setSearchText(ev.target.value)}
                />
                <button
                  type="button"
                  className={`btn ${unreadOnly ? "btn-warning" : "btn-outline-secondary"}`}
                  title="Unread only"
                  aria-pressed={unreadOnly}
                  onClick={() => setUnreadOnly((v) => !v)}
                >
                  <i className="bi bi-envelope-fill" aria-hidden="true" />
                </button>
              </div>
              {list.isLoading ? (
                <div className="small text-muted">Loading…</div>
              ) : threads.length === 0 ? (
                <div className="small text-muted">No threads match.</div>
              ) : (
                <div className="list-group board-mail-threads">
                  {threads.map((t) => (
                    <button
                      key={t.threadId}
                      type="button"
                      className={`list-group-item list-group-item-action py-2 ${t.threadId === activeId ? "active" : ""} ${t.unread ? "board-mail-unread" : ""}`}
                      onClick={() => selectThread(t.threadId)}
                    >
                      <div className="d-flex justify-content-between gap-2">
                        <span className="text-truncate">
                          {t.unread ? <i className="bi bi-circle-fill text-warning me-1 small" role="img" aria-label="unread" /> : null}
                          {t.subject}
                        </span>
                        <span className="small text-nowrap opacity-75">{t.lastMessageAt.slice(0, 10)}</span>
                      </div>
                      <div className="small text-truncate opacity-75">{senderLabel(t)}</div>
                      <div className="small d-flex gap-2 opacity-75">
                        <span className="badge text-bg-light border text-body fw-normal">{mailboxShortLabel(t.mailbox, status.domain)}</span>
                        {t.messageCount > 1 ? <span>{t.messageCount} messages</span> : null}
                        {t.hasAttachments ? <i className="bi bi-paperclip" role="img" aria-label="has attachments" /> : null}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="col-12 col-lg-7 col-xl-8">
              {!activeId ? (
                <div className="text-muted small border rounded p-3 h-100 d-flex align-items-center justify-content-center">
                  Select a thread to read it.
                </div>
              ) : thread.isLoading ? (
                <div className="small text-muted">Loading thread…</div>
              ) : thread.isError || !thread.data ? (
                <div className="alert alert-danger py-2 small">{errorText(thread.error) ?? "Thread not found."}</div>
              ) : (
                <ThreadPane
                  data={thread.data}
                  masked={showMasked ? maskedThread.data?.messages : undefined}
                  maskedLoading={showMasked && maskedThread.isLoading}
                  showMasked={showMasked}
                  onToggleMasked={setShowMasked}
                  domain={status.domain}
                  onMarkRead={(read) => markRead.mutate({ threadId: thread.data!.thread.threadId, read })}
                  isMarking={markRead.isPending}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ThreadPane({
  data,
  masked,
  maskedLoading,
  showMasked,
  onToggleMasked,
  domain,
  onMarkRead,
  isMarking,
}: {
  readonly data: BoardMailThreadPayload;
  readonly masked: readonly BoardMailMaskedMessage[] | undefined;
  readonly maskedLoading: boolean;
  readonly showMasked: boolean;
  readonly onToggleMasked: (show: boolean) => void;
  readonly domain: string;
  readonly onMarkRead: (read: boolean) => void;
  readonly isMarking: boolean;
}) {
  const { thread, messages } = data;
  return (
    <div>
      <div className="d-flex flex-wrap align-items-start gap-2">
        <div className="flex-grow-1">
          <div className="fw-semibold">{thread.subject}</div>
          <div className="small text-muted">
            <span className="badge text-bg-light border text-body fw-normal me-2">{mailboxShortLabel(thread.mailbox, domain)}</span>
            {thread.participants.join(", ")}
            <span className="ms-2">· {thread.messageCount} message{thread.messageCount === 1 ? "" : "s"}</span>
          </div>
        </div>
        <div className="d-flex gap-2 align-items-center">
          <div className="form-check form-switch small mb-0" title="Show the pseudonymised text a board member receives">
            <input
              className="form-check-input"
              type="checkbox"
              id="board-mail-show-masked"
              checked={showMasked}
              onChange={(ev) => onToggleMasked(ev.target.checked)}
            />
            <label className="form-check-label" htmlFor="board-mail-show-masked">
              Board's view
            </label>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary"
            disabled={isMarking}
            onClick={() => onMarkRead(thread.unread)}
            title={thread.unread ? "Mark as read" : "Mark as unread"}
          >
            <i className={`bi ${thread.unread ? "bi-envelope-open" : "bi-envelope"}`} aria-hidden="true" />
            <span className="ms-1">{thread.unread ? "Mark read" : "Mark unread"}</span>
          </button>
        </div>
      </div>
      {showMasked ? (
        <div className="small text-muted mt-2">
          <i className="bi bi-incognito me-1" aria-hidden="true" />
          This is what a board member sees: contacts become <code>contact#N</code>, phone numbers <code>phone#N</code>.
          Aliases are stable, so the board can refer to the same parent across threads.
        </div>
      ) : null}
      <ul className="list-group list-group-flush mt-2">
        {showMasked
          ? maskedLoading || !masked
            ? <li className="list-group-item px-0 small text-muted">Loading the board's view…</li>
            : masked.map((m) => <MessageCard key={m.messageId} message={m} masked />)
          : messages.map((m) => <MessageCard key={m.messageId} message={m} masked={false} />)}
      </ul>
    </div>
  );
}
