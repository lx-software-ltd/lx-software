import type { ReactNode } from "react";

export type AdminExpandableRowProps = {
  readonly colSpan: number;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly children: ReactNode;
  readonly editor: ReactNode;
};

/**
 * Summary row plus, when open, a detail row framed with the summary.
 * Clicking the row toggles. Clicks inside the editor do not.
 */
export function AdminExpandableRow({
  colSpan,
  expanded,
  onToggle,
  children,
  editor,
}: AdminExpandableRowProps) {
  return (
    <>
      <tr
        className={expanded ? "admin-row-framed" : undefined}
        onClick={onToggle}
      >
        {children}
      </tr>
      {expanded ? (
        <tr className="admin-row-detail-framed">
          <td colSpan={colSpan} className="p-0">
            <div className="admin-expand is-open">
              <div className="admin-expand-inner p-3" onClick={(event) => event.stopPropagation()}>
                {editor}
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
