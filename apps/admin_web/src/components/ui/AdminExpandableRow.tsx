import { useId, useRef, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";

export type AdminExpandableRowProps = {
  readonly colSpan: number;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly children: ReactNode;
  readonly editor: ReactNode;
};

function selectionText(): string {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return "";
  return selection.toString();
}

/**
 * One record: a focusable summary row plus, when open, a detail row.
 * Each record is its own `<tbody>` so zebra striping follows records.
 * Clicking the row toggles. Dragging to select text, and clicks inside the editor, do not.
 */
export function AdminExpandableRow({
  colSpan,
  expanded,
  onToggle,
  children,
  editor,
}: AdminExpandableRowProps) {
  const detailId = useId();
  const pointerDown = useRef<{ x: number; y: number } | null>(null);

  function toggleFromRow() {
    if (selectionText().trim().length > 0) return;
    onToggle();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableRowElement>) {
    if (event.target !== event.currentTarget) return;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onToggle();
  }

  function onMouseDown(event: MouseEvent<HTMLTableRowElement>) {
    pointerDown.current = { x: event.clientX, y: event.clientY };
  }

  function onClick(event: MouseEvent<HTMLTableRowElement>) {
    const down = pointerDown.current;
    pointerDown.current = null;
    if (down) {
      const moved = Math.abs(event.clientX - down.x) > 4 || Math.abs(event.clientY - down.y) > 4;
      if (moved) return;
    }
    toggleFromRow();
  }

  return (
    <tbody className="admin-record-group">
      <tr
        className={expanded ? "admin-expand-summary admin-row-framed" : "admin-expand-summary"}
        tabIndex={0}
        aria-expanded={expanded}
        aria-controls={expanded ? detailId : undefined}
        onKeyDown={onKeyDown}
        onMouseDown={onMouseDown}
        onClick={onClick}
      >
        {children}
      </tr>
      {expanded ? (
        <tr id={detailId} className="admin-row-detail-framed">
          <td colSpan={colSpan} className="p-0">
            <div className="admin-expand is-open">
              <div className="admin-expand-inner p-3" onClick={(event) => event.stopPropagation()}>
                {editor}
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </tbody>
  );
}

(AdminExpandableRow as { recordGroup?: boolean }).recordGroup = true;
