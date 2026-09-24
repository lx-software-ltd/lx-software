import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  adminTabButtonId,
  nextTabIdForKey,
} from "../../lib/adminTabs";
import { useAdminChrome } from "./AdminChrome";

export type AdminTabBadge = {
  readonly value: number | string;
  readonly tone?: "neutral" | "warning";
};

export type AdminTabItem<T extends string> = {
  readonly id: T;
  readonly label: string;
  /** Bootstrap Icons class without the `bi` prefix, e.g. `bi-list-check`. */
  readonly icon?: string;
  readonly badge?: AdminTabBadge;
};

export type AdminTabListProps<T extends string> = {
  readonly tabs: readonly AdminTabItem<T>[];
  readonly active: T;
  readonly onChange: (id: T) => void;
  readonly className?: string;
  /** Accessible name of the list, e.g. "Finance sections". */
  readonly label: string;
  /** Indent under a parent section in the rail (Executive Board under Siu Tin Dei). */
  readonly nested?: boolean;
  /**
   * Stable prefix for tab button ids. Pass the same value to
   * `adminTabButtonId(prefix, active)` for the panel's `aria-labelledby`.
   */
  readonly idPrefix?: string;
  /** `id` of the element that renders the active tab's content. */
  readonly panelId?: string;
  /** When all controls should be non-interactive (e.g. data failed to load). */
  readonly disabled?: boolean;
};

function badgeClass(tone: AdminTabBadge["tone"]): string {
  return tone === "warning"
    ? "badge rounded-pill text-bg-warning ms-1"
    : "badge rounded-pill text-bg-light border ms-1";
}

/**
 * Page-section switcher following the WAI-ARIA Tabs pattern (automatic
 * activation, roving tabindex, arrow/Home/End keys).
 *
 * From `md` the tabs portal into the rail under the active page. Phones get a
 * native select so the section list stays one control tall.
 */
export function AdminTabList<T extends string>({
  tabs,
  active,
  onChange,
  className = "",
  label,
  idPrefix,
  panelId,
  disabled = false,
  nested = false,
}: AdminTabListProps<T>) {
  const generated = useId();
  const prefix = idPrefix ?? generated;
  const buttonRefs = useRef(new Map<T, HTMLButtonElement>());
  const { slot } = useAdminChrome();
  const ids = tabs.map((t) => t.id);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const next = nextTabIdForKey(event.key, ids, active);
    if (!next) return;
    event.preventDefault();
    onChange(next);
    buttonRefs.current.get(next)?.focus();
  };

  const selectId = `${prefix}-select`;

  const list: ReactNode = (
      <ul
        className={`admin-rail-tabs${nested ? " admin-rail-nested" : ""}`}
        role="tablist"
        aria-label={label}
      >
        {tabs.map((item) => {
          const isActive = item.id === active;
          return (
            <li key={item.id} className="nav-item" role="presentation">
              <button
                ref={(el) => {
                  if (el) buttonRefs.current.set(item.id, el);
                  else buttonRefs.current.delete(item.id);
                }}
                id={adminTabButtonId(prefix, item.id)}
                type="button"
                className={`nav-link admin-tab ${isActive ? "active" : ""}`.trim()}
                role="tab"
                aria-selected={isActive}
                aria-controls={panelId}
                aria-disabled={disabled || undefined}
                tabIndex={isActive ? 0 : -1}
                disabled={disabled}
                onClick={() => onChange(item.id)}
                onKeyDown={onKeyDown}
              >
                {item.icon ? <i className={`bi ${item.icon}`} aria-hidden="true" /> : null}
                <span>{item.label}</span>
                {item.badge ? (
                  <span className={badgeClass(item.badge.tone)}>{item.badge.value}</span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
  );

  return (
    <div className={className}>
      <div className="d-md-none admin-section-select">
        <label className="form-label small mb-1" htmlFor={selectId}>
          {label}
        </label>
        <select
          id={selectId}
          className="form-select admin-tab-select"
          value={active}
          disabled={disabled}
          onChange={(ev) => onChange(ev.target.value as T)}
        >
          {tabs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
              {item.badge ? ` (${item.badge.value})` : ""}
            </option>
          ))}
        </select>
      </div>
      {slot ? createPortal(list, slot) : list}
    </div>
  );
}
