import { useId, type ReactNode } from "react";

export type AdminPageHeaderProps = {
  readonly title: string;
  readonly eyebrow?: string;
  readonly help?: ReactNode;
  readonly actions?: ReactNode;
};

/** Page title, optional help popover, and the page's primary actions. */
export function AdminPageHeader({ title, eyebrow, help, actions }: AdminPageHeaderProps) {
  const helpId = useId();
  return (
    <header className="admin-page-header">
      <div className="admin-page-heading">
        {eyebrow ? <p className="admin-eyebrow">{eyebrow}</p> : null}
        <div className="admin-page-title-row">
          <h1 className="admin-page-title">{title}</h1>
          {help ? (
            <>
              <button
                type="button"
                className="admin-help-btn"
                popoverTarget={helpId}
                aria-label="About this page"
              >
                ?
              </button>
              <div id={helpId} popover="auto" className="admin-help-popover">
                {help}
              </div>
            </>
          ) : null}
        </div>
      </div>
      {actions ? <div className="admin-page-actions">{actions}</div> : null}
    </header>
  );
}
