import { useState } from "react";
import { shortTaskId } from "../../lib/boardModel";

export function BoardTaskId({
  taskId,
  compact = false,
  full = false,
}: {
  readonly taskId: string;
  readonly compact?: boolean;
  readonly full?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const short = shortTaskId(taskId);
  const label = full ? taskId : `#${short}`;
  return (
    <span className={`board-task-id ${compact ? "board-task-id-compact" : ""}`.trim()}>
      <code className="board-task-id-code" title={taskId} aria-label={`Task ${taskId}`}>
        {label}
      </code>
      <button
        type="button"
        className="btn btn-sm btn-link p-0 ms-1 lh-1 board-task-id-copy"
        aria-label={`Copy task id ${taskId}`}
        title={copied ? "Copied" : "Copy task id"}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          void copyTaskId(taskId).then((ok) => {
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

async function copyTaskId(taskId: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(taskId);
      return true;
    }
  } catch {
    return false;
  }
  return false;
}
