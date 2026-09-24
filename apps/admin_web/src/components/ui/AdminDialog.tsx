import { useEffect, useId, useRef, type ReactNode } from "react";

export type AdminDialogProps = {
  readonly open: boolean;
  readonly title: string;
  readonly onClose: () => void;
  readonly children: ReactNode;
};

/** Native dialog for forms that used to sit above a table. */
export function AdminDialog({ open, title, onClose, children }: AdminDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="admin-form-dialog"
      aria-labelledby={titleId}
      onClose={onClose}
    >
      <div className="d-flex align-items-start justify-content-between gap-3 mb-3">
        <h2 id={titleId} className="h5 mb-0">
          {title}
        </h2>
        <button type="button" className="btn-close" aria-label="Close" onClick={onClose} />
      </div>
      {children}
    </dialog>
  );
}
