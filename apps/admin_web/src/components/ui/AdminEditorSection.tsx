import type { ReactNode, Ref } from "react";

export type AdminEditorSectionProps = {
  readonly title?: string;
  readonly description?: string;
  readonly children: ReactNode;
  /** Primary actions (Save / Update). Placed at the **bottom-left** of the section. */
  readonly footer?: ReactNode;
  /** Root `.card` element; use with `scheduleFocusRecordEditor` when opening a row for edit. */
  readonly containerRef?: Ref<HTMLDivElement | null>;
  /** Omit the card chrome when the form already sits inside another panel. */
  readonly embedded?: boolean;
};

/**
 * Editor chrome: content first, then a footer row with actions aligned to the start.
 * Use for forms that sit **above** data tables.
 */
export function AdminEditorSection({
  title,
  description,
  children,
  footer,
  containerRef,
  embedded = false,
}: AdminEditorSectionProps) {
  const heading = title ? (
    <h2 className="h6 text-uppercase text-muted mb-2">{title}</h2>
  ) : null;
  const intro = description ? (
    <p className="small text-muted mb-3">{description}</p>
  ) : null;
  const actions = footer ? (
    <div
      className={`d-flex justify-content-start align-items-center gap-2 flex-wrap ${
        embedded ? "mt-3" : "card-footer bg-transparent border-top pt-3 pb-3"
      }`}
    >
      {footer}
    </div>
  ) : null;
  if (embedded) {
    return (
      <div ref={containerRef}>
        {heading}
        {intro}
        {children}
        {actions}
      </div>
    );
  }
  return (
    <div ref={containerRef} className="card shadow-sm mb-4">
      <div className="card-body">
        {heading}
        {intro}
        {children}
      </div>
      {actions}
    </div>
  );
}
