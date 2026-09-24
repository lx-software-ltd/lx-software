import { useId, useRef } from "react";
import { TableIconButton } from "./TableIconButton";

export type AdminRowAction = {
  readonly id: string;
  readonly label: string;
  readonly iconClassName: string;
  readonly onClick: () => void;
  readonly danger?: boolean;
  readonly hidden?: boolean;
  readonly disabled?: boolean;
};

export type AdminRowActionsProps = {
  readonly actions: readonly AdminRowAction[];
};

/** Icon actions. More than two: the first stays inline and the rest go in a menu. */
export function AdminRowActions({ actions }: AdminRowActionsProps) {
  const menuId = useId();
  const moreRef = useRef<HTMLButtonElement>(null);
  const visible = actions.filter((action) => !action.hidden);
  if (visible.length === 0) return null;
  const [first, ...rest] = visible;
  if (!first) return null;

  return (
    <div
      className="d-inline-flex align-items-center gap-1 admin-row-actions"
      onClick={(event) => event.stopPropagation()}
    >
      <TableIconButton
        iconClassName={first.iconClassName}
        ariaLabel={first.label}
        variant={first.danger ? "danger" : "default"}
        onClick={first.onClick}
        disabled={first.disabled}
      />
      {rest.length === 1 && rest[0] ? (
        <TableIconButton
          iconClassName={rest[0].iconClassName}
          ariaLabel={rest[0].label}
          variant={rest[0].danger ? "danger" : "default"}
          onClick={rest[0].onClick}
          disabled={rest[0].disabled}
        />
      ) : null}
      {rest.length > 1 ? (
        <>
          <button
            ref={moreRef}
            type="button"
            className="btn btn-sm btn-outline-secondary bg-white admin-table-icon-btn"
            aria-label="More actions"
            title="More actions"
            popoverTarget={menuId}
          >
            <i className="bi bi-three-dots" aria-hidden="true" />
          </button>
          <div
            id={menuId}
            popover="auto"
            className="admin-row-menu"
            onToggle={(event) => {
              const menu = event.currentTarget;
              const button = moreRef.current;
              if (!menu.matches(":popover-open") || !button) return;
              const rect = button.getBoundingClientRect();
              const width = menu.offsetWidth || 192;
              menu.style.top = `${rect.bottom + 4}px`;
              menu.style.left = `${Math.max(8, rect.right - width)}px`;
            }}
          >
            {rest.map((action) => (
              <button
                key={action.id}
                type="button"
                className={`admin-row-menu-item${action.danger ? " text-danger" : ""}`}
                onClick={action.onClick}
                disabled={action.disabled}
              >
                <i className={action.iconClassName} aria-hidden="true" />
                {action.label}
              </button>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
