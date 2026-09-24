import { useEffect, useId, useRef } from "react";

export type ConfirmDialogProps = {
  readonly open: boolean;
  readonly title: string;
  readonly body: string;
  readonly confirmLabel: string;
  readonly cancelLabel?: string;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
  readonly confirmBusy?: boolean;
  readonly tone?: "primary" | "danger";
};

/** Modal confirm/cancel. Native `<dialog>` traps focus and closes on Escape. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  onCancel,
  confirmBusy = false,
  tone = "primary",
}: ConfirmDialogProps) {
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
      className="admin-confirm-dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        if (!confirmBusy) onCancel();
      }}
    >
      <h2 id={titleId} className="h6 mb-2">
        {title}
      </h2>
      <p className="mb-3">{body}</p>
      <div className="d-flex justify-content-start gap-2">
        <button
          type="button"
          className={`btn btn-sm ${tone === "danger" ? "btn-danger" : "btn-primary"}`}
          onClick={onConfirm}
          disabled={confirmBusy}
          aria-busy={confirmBusy}
        >
          {confirmBusy ? `${confirmLabel}…` : confirmLabel}
        </button>
        <button
          type="button"
          className="btn btn-sm btn-outline-secondary"
          onClick={onCancel}
          disabled={confirmBusy}
        >
          {cancelLabel}
        </button>
      </div>
    </dialog>
  );
}
