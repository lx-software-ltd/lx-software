import type { FormEvent, ReactNode } from "react";

export type AdminFieldGridProps = {
  readonly columns: 1 | 2 | 4;
  readonly children: ReactNode;
};

export function AdminFieldGrid({ columns, children }: AdminFieldGridProps) {
  return <div className={`row g-2 admin-field-grid admin-field-grid-${columns}`}>{children}</div>;
}

export type AdminFieldProps = {
  readonly children: ReactNode;
  /** Width inside the grid. Defaults to one column. */
  readonly span?: 1 | 2 | 4;
};

export function AdminField({ children, span = 1 }: AdminFieldProps) {
  return <div className={`admin-field admin-field-span-${span}`}>{children}</div>;
}

export type AdminEditorActionsProps = {
  readonly formId: string;
  readonly submitLabel: string;
  readonly isSaving?: boolean;
  readonly savingLabel?: string;
  readonly disabled?: boolean;
};

export function AdminEditorActions({
  formId,
  submitLabel,
  isSaving = false,
  savingLabel = "Saving…",
  disabled = false,
}: AdminEditorActionsProps) {
  return (
    <div className="d-flex justify-content-start align-items-center gap-2 mt-3">
      <button
        type="submit"
        form={formId}
        className="btn btn-primary btn-sm"
        disabled={disabled || isSaving}
        aria-busy={isSaving}
      >
        {isSaving ? (
          <>
            <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />
            {savingLabel}
          </>
        ) : (
          submitLabel
        )}
      </button>
    </div>
  );
}

export type AdminEditorPanelProps = {
  readonly children: ReactNode;
  readonly formId: string;
  readonly onSubmit: (event: FormEvent) => void;
  readonly submitLabel: string;
  readonly isSaving?: boolean;
  readonly savingLabel?: string;
  readonly error?: string | null;
};

/** Field labels and fields, then one primary action. No title and no Cancel. */
export function AdminEditorPanel({
  children,
  formId,
  onSubmit,
  submitLabel,
  isSaving,
  savingLabel,
  error,
}: AdminEditorPanelProps) {
  return (
    <div className="admin-editor-panel">
      {error ? (
        <div className="alert alert-danger py-2 small" role="alert">
          {error}
        </div>
      ) : null}
      <form id={formId} onSubmit={onSubmit}>
        {children}
      </form>
      <AdminEditorActions
        formId={formId}
        submitLabel={submitLabel}
        isSaving={isSaving}
        savingLabel={savingLabel}
      />
    </div>
  );
}
