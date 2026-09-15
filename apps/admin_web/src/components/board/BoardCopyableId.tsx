import { useState } from "react";
import { shortTaskId } from "../../lib/boardModel";

export function BoardCopyableId({
  id,
  noun,
  compact = false,
  full = false,
}: {
  readonly id: string;
  readonly noun: string;
  readonly compact?: boolean;
  readonly full?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const short = shortTaskId(id);
  const label = full ? id : `#${short}`;
  const nounLower = noun.toLowerCase();
  return (
    <span className={`board-task-id ${compact ? "board-task-id-compact" : ""}`.trim()}>
      <code className="board-task-id-code" title={id} aria-label={`${noun} ${id}`}>
        {label}
      </code>
      <button
        type="button"
        className="btn btn-sm btn-link p-0 ms-1 lh-1 board-task-id-copy"
        aria-label={`Copy ${nounLower} id ${id}`}
        title={copied ? "Copied" : `Copy ${nounLower} id`}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void copyBoardId(id).then((ok) => {
            if (!ok) return;
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        <i className={copied ? "bi bi-check2" : "bi bi-clipboard"} aria-hidden="true" />
      </button>
    </span>
  );
}

async function copyBoardId(id: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(id);
      return true;
    }
  } catch {
    // HTTP or denied clipboard: fall through to execCommand.
  }
  try {
    const el = document.createElement("textarea");
    el.value = id;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.top = "0";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    el.setSelectionRange(0, id.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  } catch {
    return false;
  }
}
