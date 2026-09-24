export type TableIconButtonProps = {
  readonly iconClassName: string;
  /** Accessible name (required because there is no visible label). */
  readonly ariaLabel: string;
  readonly onClick?: () => void;
  readonly variant?: "default" | "danger";
  /** Bordered white buttons are the record-table operations. Other tables stay link-style. */
  readonly appearance?: "link" | "bordered";
  readonly type?: "button" | "submit";
  readonly disabled?: boolean;
};

/** Icon-only control for the operations column (must pair with `aria-label`). */
export function TableIconButton({
  iconClassName,
  ariaLabel,
  onClick,
  variant = "default",
  appearance = "link",
  type = "button",
  disabled,
}: TableIconButtonProps) {
  const bordered = appearance === "bordered";
  return (
    <button
      type={type}
      className={`btn btn-sm admin-table-icon-btn ${
        bordered
          ? `btn-outline-secondary bg-white${variant === "danger" ? " text-danger border-danger" : ""}`
          : `btn-link p-1 lh-1${variant === "danger" ? " text-danger" : ""}`
      }`}
      aria-label={ariaLabel}
      title={ariaLabel}
      onClick={onClick}
      disabled={disabled}
    >
      <i className={iconClassName} aria-hidden="true" />
    </button>
  );
}
