import { useEffect, useRef, type ReactNode } from "react";

export type AdminDisclosureProps = {
  readonly title: string;
  readonly children: ReactNode;
  readonly defaultOpen?: boolean;
};

/** The summary is the only heading for the block. */
export function AdminDisclosure({ title, children, defaultOpen = false }: AdminDisclosureProps) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (defaultOpen && ref.current) ref.current.open = true;
  }, [defaultOpen]);
  return (
    <details ref={ref} className="admin-disclosure">
      <summary>{title}</summary>
      <div className="admin-disclosure-body">{children}</div>
    </details>
  );
}
