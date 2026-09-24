import type { ReactNode } from "react";

export type AdminFilterFieldProps = {
  readonly label: string;
  readonly htmlFor: string;
  readonly children: ReactNode;
};

export function AdminFilterField({ label, htmlFor, children }: AdminFilterFieldProps) {
  return (
    <div className="admin-filter-field">
      <label className="form-label small mb-1" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
    </div>
  );
}

export type AdminFilterBarProps = {
  readonly children?: ReactNode;
  readonly create?: ReactNode;
  readonly trailing?: ReactNode;
};

/** Filters on one desktop line. Create sits above them at full width on a phone. */
export function AdminFilterBar({ children, create, trailing }: AdminFilterBarProps) {
  return (
    <search className="admin-filter-bar">
      {create ? <div className="admin-filter-create">{create}</div> : null}
      {children ? <div className="admin-filter-fields">{children}</div> : null}
      {trailing ? <div className="admin-filter-trailing">{trailing}</div> : null}
    </search>
  );
}

export type AdminCreateButtonProps = {
  readonly label: string;
  readonly onClick: () => void;
  readonly disabled?: boolean;
};

export function AdminCreateButton({ label, onClick, disabled }: AdminCreateButtonProps) {
  return (
    <button
      type="button"
      className="btn btn-primary btn-sm admin-create-btn"
      onClick={onClick}
      disabled={disabled}
    >
      {label}
    </button>
  );
}

export type AdminRecordTableProps = {
  /** Accessible name for the untitled card. The page or tab already shows the visible title. */
  readonly label: string;
  readonly filters?: ReactNode;
  /** Import tools and other blocks between the filters and the table. */
  readonly beforeTable?: ReactNode;
  readonly children: ReactNode;
  /** Nested list inside an open editor: no card chrome. */
  readonly embedded?: boolean;
};

export function AdminRecordTable({
  label,
  filters,
  beforeTable,
  children,
  embedded = false,
}: AdminRecordTableProps) {
  const body = (
    <>
      {filters ? <div className={embedded ? "pb-3" : "card-body py-3 border-bottom"}>{filters}</div> : null}
      {beforeTable ? (
        <div className={embedded ? "py-2" : "card-body py-3 border-bottom"}>{beforeTable}</div>
      ) : null}
      {children}
    </>
  );
  if (embedded) {
    return (
      <div className="admin-record-table admin-record-table-embedded" aria-label={label}>
        {body}
      </div>
    );
  }
  return (
    <section className="card shadow-sm mb-4 admin-record-table" aria-label={label}>
      {body}
    </section>
  );
}
