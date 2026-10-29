import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { DateTimeDisplay } from "../ui";
import { BoardMarkdown } from "./BoardMarkdown";
import { BoardOffcanvas } from "./BoardOffcanvas";
import { BoardToolCallList } from "./BoardToolCallList";
import { useBoardChat } from "../../hooks/useBoardChat";
import { getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { formatUsageCost, memberInitials, type BoardMeetingMode, type BoardMember } from "../../lib/boardModel";
import { BOARD_MAX_CHAT_MESSAGE_LEN } from "../../lib/contracts/generated";

export type BoardChatOffcanvasProps = {
  readonly member: BoardMember | null;
  readonly isChair: boolean;
  /** Tool ids this member may use (effective level above "off"); shown in the empty-thread hint. */
  readonly toolLabels?: readonly string[];
  readonly onClose: () => void;
  readonly onStartMeeting: (mode: BoardMeetingMode, topic: string) => void;
  readonly onOpenApproval?: (approvalId: string) => void;
};

export function BoardChatOffcanvas({ member, isChair, toolLabels = [], onClose, onStartMeeting, onOpenApproval }: BoardChatOffcanvasProps) {
  const personaId = member?.id ?? null;
  const { messages, isLoading, isError, error, send, clear } = useBoardChat(personaId);
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const pendingCallCount = messages.reduce((n, m) => (m.isPending ? n + (m.toolCalls?.length ?? 0) : n), 0);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, send.isPending, pendingCallCount]);

  if (!member) return null;

  const submit = (ev?: FormEvent) => {
    ev?.preventDefault();
    const text = draft.trim();
    if (!text || send.isPending) return;
    setDraft("");
    send.mutate(text);
  };

  const onKeyDown = (ev: KeyboardEvent<HTMLTextAreaElement>) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      submit();
    }
  };

  const sendError = send.error ? getAdminApiErrorMessage(send.error) ?? send.error.message : null;

  return (
    <BoardOffcanvas
      isOpen
      wide
      title={
        <span className="d-inline-flex align-items-center gap-2">
          <span className="board-avatar board-avatar-sm" aria-hidden="true">{memberInitials(member)}</span>
          {member.displayName}
        </span>
      }
      subtitle={`${member.title}${isChair ? " · chair" : ""}`}
      onClose={onClose}
      footer={
        <form className="w-100 d-flex flex-column gap-2" onSubmit={submit}>
          <textarea
            className="form-control"
            rows={2}
            value={draft}
            maxLength={BOARD_MAX_CHAT_MESSAGE_LEN}
            placeholder={`Ask ${member.displayName}… (Enter to send, Shift+Enter for a new line)`}
            aria-label={`Message to ${member.displayName}`}
            disabled={send.isPending}
            onChange={(ev) => setDraft(ev.target.value)}
            onKeyDown={onKeyDown}
          />
          <div className="d-flex justify-content-between align-items-center">
            <button
              type="button"
              className="btn btn-link btn-sm text-danger px-0"
              disabled={messages.length === 0 || clear.isPending || send.isPending}
              onClick={() => clear.mutate()}
            >
              Clear thread
            </button>
            <button type="submit" className="btn btn-primary btn-sm" disabled={!draft.trim() || send.isPending}>
              {send.isPending ? "Thinking…" : "Send"}
            </button>
          </div>
          {sendError ? <div className="alert alert-danger py-1 small mb-0">{sendError}</div> : null}
        </form>
      }
    >
      {isLoading ? (
        <div className="text-muted small">Loading thread…</div>
      ) : isError ? (
        <div className="alert alert-danger small">{getAdminApiErrorMessage(error) ?? "Could not load the thread."}</div>
      ) : messages.length === 0 ? (
        <div className="text-muted small">
          <p className="mb-1">
            Start a conversation. {member.displayName} knows the company brief, your updates, open actions
            and the last minutes, and answers from this mandate:
          </p>
          <blockquote className="border-start ps-2 mb-0">{member.mandate}</blockquote>
          {toolLabels.length > 0 ? (
            <p className="mt-2 mb-0">
              <i className="bi bi-tools me-1" aria-hidden="true" />
              Can look things up in {toolLabels.join(", ")} while answering.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="d-flex flex-column gap-3">
          {messages.map((m) => (
            <div key={m.messageId} className={`board-chat-row ${m.role === "user" ? "board-chat-row-user" : ""}`}>
              <div
                className={`board-chat-bubble ${m.role === "user" ? "board-chat-bubble-user" : ""}`}
                aria-live={m.isPending ? "polite" : undefined}
              >
                {m.isPending ? (
                  m.toolCalls && m.toolCalls.length > 0 ? (
                    <BoardToolCallList calls={m.toolCalls} isLive className="small" />
                  ) : (
                    <span className="d-inline-flex align-items-center gap-2 text-muted small">
                      <span className="spinner-border spinner-border-sm" aria-hidden="true" />
                      {member.displayName} is thinking…
                    </span>
                  )
                ) : m.role === "assistant" ? (
                  <>
                    {m.toolCalls && m.toolCalls.length > 0 ? (
                      <BoardToolCallList calls={m.toolCalls} onOpenApproval={onOpenApproval} className="small text-muted mb-2" />
                    ) : null}
                    <BoardMarkdown text={m.text} className="small" />
                  </>
                ) : (
                  <div className="small board-prewrap">{m.text}</div>
                )}
                {!m.isPending ? (
                  <div className="board-chat-meta text-muted">
                    <DateTimeDisplay iso={m.createdAt} />
                    {m.usage ? <span> · {formatUsageCost(m.usage.cost)}</span> : null}
                  </div>
                ) : null}
                {m.suggestedMeeting ? (
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-primary mt-2"
                    onClick={() => onStartMeeting(m.suggestedMeeting!.mode, m.suggestedMeeting!.topic)}
                  >
                    <i className="bi bi-people me-1" aria-hidden="true" />
                    Start {m.suggestedMeeting.mode === "deepDive" ? "deep dive" : "stand-up"}
                    {m.suggestedMeeting.topic ? `: ${m.suggestedMeeting.topic}` : ""}
                  </button>
                ) : null}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}
    </BoardOffcanvas>
  );
}
