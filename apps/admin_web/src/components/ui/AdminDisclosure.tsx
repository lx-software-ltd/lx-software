import { useEffect, useRef, useState, type ReactNode } from "react";
import { AdminDialog } from "./AdminDialog";

export type AdminDisclosureProps = {
  readonly title: string;
  readonly children: ReactNode;
  readonly defaultOpen?: boolean;
  /** `dialog` opens the body in a modal instead of an inline disclosure. */
  readonly presentation?: "inline" | "dialog";
};

/** The summary is the only heading for the block. */
export function AdminDisclosure({
  title,
  children,
  defaultOpen = false,
  presentation = "inline",
}: AdminDisclosureProps) {
  const ref = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => {
    if (defaultOpen && ref.current) ref.current.open = true;
  }, [defaultOpen]);
  if (presentation === "dialog") {
    return (
      <>
        <button type="button" className="btn btn-outline-secondary" onClick={() => setOpen(true)}>
          {title}
        </button>
        <AdminDialog open={open} title={title} onClose={() => setOpen(false)}>
          {children}
        </AdminDialog>
      </>
    );
  }
  return (
    <details ref={ref} className="admin-disclosure" open={defaultOpen || undefined}>
      <summary>{title}</summary>
      <div className="admin-disclosure-body">{children}</div>
    </details>
  );
}
