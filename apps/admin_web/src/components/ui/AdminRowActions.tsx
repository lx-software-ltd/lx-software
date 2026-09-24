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
  /** Keep this action as its own button when the rest sit in the menu. */
  readonly inline?: boolean;
};

export type AdminRowActionsProps = {
  readonly actions: readonly AdminRowAction[];
};

/** Icon actions. One action stays inline. Several collapse into one menu. */
export function AdminRowActions({ actions }: AdminRowActionsProps) {
  const menuId = useId();
  const moreRef = useRef<HTMLButtonElement>(null);
  const visible = actions.filter((action) => !action.hidden);
  if (visible.length === 0) return null;
  const solo = visible.length === 1 ? visible[0] : null;
  const inline = solo ? [] : visible.filter((action) => action.inline);
  const menuActions = solo ? [] : visible.filter((action) => !action.inline);

  const hideMenu = (menu: HTMLElement | null) => {
    if (!menu || typeof menu.hidePopover !== "function") return;
    try {
      if (menu.matches(":popover-open")) menu.hidePopover();
    } catch {
      // Already closed.
    }
  };

  return (
    <div
      className="d-inline-flex align-items-center gap-1 admin-row-actions"
      onClick={(event) => event.stopPropagation()}
    >
      {solo ? (
        <TableIconButton
          iconClassName={solo.iconClassName}
          ariaLabel={solo.label}
          appearance="bordered"
          variant={solo.danger ? "danger" : "default"}
          onClick={solo.onClick}
          disabled={solo.disabled}
        />
      ) : null}
      {inline.map((action) => (
        <TableIconButton
          key={action.id}
          iconClassName={action.iconClassName}
          ariaLabel={action.label}
          appearance="bordered"
          variant={action.danger ? "danger" : "default"}
          onClick={action.onClick}
          disabled={action.disabled}
        />
      ))}
      {menuActions.length > 0 ? (
        <>
          <button
            ref={moreRef}
            type="button"
            className="admin-kebab"
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
            onBeforeToggle={(event) => {
              if (event.newState !== "open") return;
              const button = moreRef.current;
              if (!button) return;
              const rect = button.getBoundingClientRect();
              const menu = event.currentTarget;
              const width = menu.offsetWidth || 192;
              menu.style.top = `${rect.bottom + 4}px`;
              menu.style.left = `${Math.max(8, rect.right - width)}px`;
            }}
          >
            {menuActions.map((action) => (
              <button
                key={action.id}
                type="button"
                className={`admin-row-menu-item${action.danger ? " text-danger" : ""}`}
                onClick={(event) => {
                  hideMenu(event.currentTarget.closest("[popover]"));
                  action.onClick();
                }}
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

