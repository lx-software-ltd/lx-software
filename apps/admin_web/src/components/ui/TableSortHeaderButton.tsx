export type TableSortHeaderButtonProps = {
  readonly label: string;
  readonly isActive: boolean;
  readonly direction: "asc" | "desc" | null;
  readonly onClick: () => void;
  readonly align?: "start" | "end";
};

/** Icon-only sort control for table column headers (Bootstrap link button). */
export function TableSortHeaderButton({
  label,
  isActive,
  direction,
  onClick,
  align = "start",
}: TableSortHeaderButtonProps) {
  const iconClass =
    direction === "asc"
      ? "bi bi-arrow-up"
      : direction === "desc"
        ? "bi bi-arrow-down"
        : "";
  const alignClass = align === "end" ? "w-100 text-end" : "text-start";
  return (
    <>
      <span className={`d-md-none admin-nowrap ${align === "end" ? "d-inline-block w-100 text-end" : ""}`}>
        {label}
      </span>
      <button
        type="button"
        className={`btn btn-link admin-sort-header p-0 text-decoration-none fw-semibold d-none d-md-inline-block ${alignClass}`}
        onClick={onClick}
        aria-label={
          isActive
            ? `Sorted by ${label}, ${direction === "asc" ? "ascending" : "descending"}. Click to reverse.`
            : `Sort by ${label}`
        }
      >
        <span className="admin-nowrap">{label}</span>
        {iconClass ? <i className={`${iconClass} ms-1`} aria-hidden /> : null}
      </button>
    </>
  );
}
