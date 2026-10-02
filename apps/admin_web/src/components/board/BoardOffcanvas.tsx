import { useEffect, type ReactNode } from "react";

export type BoardOffcanvasProps = {
  readonly isOpen: boolean;
  readonly title: ReactNode;
  readonly subtitle?: ReactNode;
  readonly onClose: () => void;
  readonly children: ReactNode;
  readonly footer?: ReactNode;
  readonly wide?: boolean;
};

/** Right-hand Bootstrap offcanvas driven by React state (no Bootstrap JS bundle). */
export function BoardOffcanvas({
  isOpen,
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide = false,
}: BoardOffcanvasProps) {
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement;
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <>
      <div className="offcanvas-backdrop fade show" onClick={onClose} aria-hidden="true" />
      <div
        className={`offcanvas offcanvas-end show board-offcanvas ${wide ? "board-offcanvas-wide" : ""}`.trim()}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="board-offcanvas-title"
        style={{ visibility: "visible" }}
      >
        <div className="offcanvas-header border-bottom">
          <div>
            <h2 className="offcanvas-title h5 mb-0" id="board-offcanvas-title">
              {title}
            </h2>
            {subtitle ? <div className="small text-muted">{subtitle}</div> : null}
          </div>
          <button type="button" className="btn-close" aria-label="Close" onClick={onClose} />
        </div>
        <div className="offcanvas-body d-flex flex-column">{children}</div>
        {footer ? <div className="border-top p-3 d-flex gap-2 flex-wrap">{footer}</div> : null}
      </div>
    </>
  );
}
