import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  type ReactNode,
  type RefObject,
  type TdHTMLAttributes,
} from "react";
import {
  adminColumnPriorityClass,
  type AdminTableColumnPriority,
} from "../../lib/adminTablePriority";

function mergeCellClass(
  ...parts: readonly (string | undefined)[]
): string | undefined {
  const merged = parts.filter((part) => part && part.length > 0).join(" ");
  return merged.length > 0 ? merged : undefined;
}

export type AdminDataTableColumn = {
  readonly key: string;
  readonly header: ReactNode;
  readonly className?: string;
  readonly headerClassName?: string;
  /**
   * Mobile-first visibility. `primary` always shows; `secondary` from `md`;
   * `tertiary` from `lg`. Pair hidden values with `AdminDataTableCellMeta`.
   * Warnings (stale badges, expiry) and the table's main metric must stay
   * reachable on phones: keep them `primary` or repeat them in the meta line.
   */
  readonly priority?: AdminTableColumnPriority;
  /** For sortable tables: maps to `<th aria-sort="…">` when set. */
  readonly thAriaSort?: "ascending" | "descending" | "none" | "other";
};

export type AdminDataTableSortDirection = "asc" | "desc";

export type AdminDataTableSort = {
  /** Sortable columns in display order; the label is what the phone select shows. */
  readonly options: readonly { readonly key: string; readonly label: string }[];
  readonly sortKey: string | null;
  readonly direction: AdminDataTableSortDirection;
  readonly onChange: (sortKey: string | null, direction: AdminDataTableSortDirection) => void;
};

export type AdminDataTableProps = {
  readonly columns: readonly AdminDataTableColumn[];
  readonly filterValue?: string;
  readonly onFilterChange?: (value: string) => void;
  readonly filterPlaceholder?: string;
  /**
   * Table markup only. The card and filter live on `AdminRecordTable` /
   * `AdminFilterBar` for record screens.
   */
  readonly bare?: boolean;
  readonly children: ReactNode;
  /**
   * When true, omit the outer card (for nesting inside `AdminEditorSection` or similar).
   * Uses slightly roomier table density than the standalone card.
   */
  readonly embedded?: boolean;
  /**
   * Sort state for tables whose headers are sort buttons. On phones the
   * secondary/tertiary headers are hidden, so the same state is exposed as a
   * compact select + direction toggle next to the filter.
   */
  readonly sort?: AdminDataTableSort;
};

const ColumnsContext = createContext<readonly AdminDataTableColumn[] | null>(null);

/**
 * Standard admin table: filter field, striped rows, last column reserved for operations.
 * Pass table body rows as `children` (typically `<tr>` elements). Use
 * `AdminCell` for body cells so column priority is applied from the column
 * definition instead of being repeated per cell.
 */
export function AdminDataTable({
  columns,
  filterValue = "",
  onFilterChange,
  filterPlaceholder = "Filter rows…",
  children,
  embedded = false,
  bare = false,
  sort,
}: AdminDataTableProps) {
  const filterId = useId();
  const sortId = useId();
  const tableRef = useRef<HTMLTableElement>(null);
  useColumnAlignmentCheck(tableRef, columns);

  const filterBlock = (
    <div className={embedded ? "pb-3 border-bottom" : "card-body py-2 border-bottom"}>
      <div className="d-flex flex-wrap gap-2 align-items-center">
        <div className="flex-grow-1 admin-table-filter">
          <label className="visually-hidden" htmlFor={filterId}>
            Filter table
          </label>
          <input
            id={filterId}
            type="search"
            className="form-control form-control-sm"
            placeholder={filterPlaceholder}
            autoComplete="off"
            value={filterValue}
            onChange={(ev) => onFilterChange?.(ev.target.value)}
          />
        </div>
        {sort ? (
          <div className="d-flex gap-1 align-items-center d-md-none admin-table-sort">
            <label className="visually-hidden" htmlFor={sortId}>
              Sort by
            </label>
            <select
              id={sortId}
              className="form-select form-select-sm"
              value={sort.sortKey ?? ""}
              onChange={(ev) => sort.onChange(ev.target.value || null, sort.direction)}
            >
              <option value="">Sort: default</option>
              {sort.options.map((o) => (
                <option key={o.key} value={o.key}>
                  Sort: {o.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary admin-table-icon-btn"
              aria-label={sort.direction === "asc" ? "Sorted ascending; switch to descending" : "Sorted descending; switch to ascending"}
              title={sort.direction === "asc" ? "Ascending" : "Descending"}
              disabled={!sort.sortKey}
              onClick={() =>
                sort.onChange(sort.sortKey, sort.direction === "asc" ? "desc" : "asc")
              }
            >
              <i
                className={`bi ${sort.direction === "asc" ? "bi-sort-alpha-down" : "bi-sort-alpha-up"}`}
                aria-hidden="true"
              />
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );

  const tableBlock = (
    <div className={embedded ? "table-responsive pt-3" : "table-responsive"}>
      <table
        ref={tableRef}
        className={`table table-striped mb-0 align-middle admin-data-table ${embedded ? "" : "table-sm"}`.trim()}
      >
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={mergeCellClass(
                  adminColumnPriorityClass(col.priority),
                  col.headerClassName ?? col.className,
                )}
                aria-sort={col.thAriaSort}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <ColumnsContext.Provider value={columns}>
          <tbody>{children}</tbody>
        </ColumnsContext.Provider>
      </table>
    </div>
  );

  const phoneSort = sort ? (
    <div className="d-flex gap-1 align-items-center d-md-none admin-table-sort px-3 pt-2">
      <label className="visually-hidden" htmlFor={sortId}>
        Sort by
      </label>
      <select
        id={sortId}
        className="form-select form-select-sm"
        value={sort.sortKey ?? ""}
        onChange={(ev) => sort.onChange(ev.target.value || null, sort.direction)}
      >
        <option value="">Sort: default</option>
        {sort.options.map((o) => (
          <option key={o.key} value={o.key}>
            Sort: {o.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn btn-sm btn-outline-secondary bg-white admin-table-icon-btn"
        aria-label={sort.direction === "asc" ? "Sorted ascending; switch to descending" : "Sorted descending; switch to ascending"}
        title={sort.direction === "asc" ? "Ascending" : "Descending"}
        disabled={!sort.sortKey}
        onClick={() =>
          sort.onChange(sort.sortKey, sort.direction === "asc" ? "desc" : "asc")
        }
      >
        <i
          className={`bi ${sort.direction === "asc" ? "bi-sort-alpha-down" : "bi-sort-alpha-up"}`}
          aria-hidden="true"
        />
      </button>
    </div>
  ) : null;

  if (bare) {
    return (
      <>
        {phoneSort}
        {tableBlock}
      </>
    );
  }

  if (embedded) {
    return (
      <>
        {onFilterChange ? filterBlock : null}
        {tableBlock}
      </>
    );
  }

  return (
    <div className="card shadow-sm">
      {filterBlock}
      {tableBlock}
    </div>
  );
}

export type AdminCellProps = Omit<TdHTMLAttributes<HTMLTableCellElement>, "className"> & {
  /** Key of the column this cell belongs to (from the table's `columns`). */
  readonly column: string;
  readonly className?: string;
};

/**
 * Body cell bound to a column key. Applies that column's priority class so
 * headers and cells always hide together; add layout classes via `className`.
 */
export function AdminCell({ column, className, children, ...rest }: AdminCellProps) {
  const columns = useContext(ColumnsContext);
  const def = columns?.find((c) => c.key === column);
  if (import.meta.env.DEV && columns && !def) {
    console.warn(`AdminCell: unknown column "${column}"`);
  }
  return (
    <td
      className={mergeCellClass(adminColumnPriorityClass(def?.priority), className)}
      data-column={column}
      {...rest}
    >
      {children}
    </td>
  );
}

/**
 * Dev-only invariant: every body row must have one cell per column (counting
 * colSpan), and each cell's priority class must match its column. Catches the
 * "header hidden, cell visible" drift that is invisible in code review.
 */
function useColumnAlignmentCheck(
  tableRef: RefObject<HTMLTableElement | null>,
  columns: readonly AdminDataTableColumn[],
) {
  const reported = useRef(new Set<string>());
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const table = tableRef.current;
    if (!table) return;
    const rows = table.querySelectorAll<HTMLTableRowElement>("tbody > tr");
    rows.forEach((row) => {
      const cells = Array.from(row.children).filter(
        (el): el is HTMLTableCellElement => el.tagName === "TD" || el.tagName === "TH",
      );
      let index = 0;
      const problems: string[] = [];
      for (const cell of cells) {
        const span = cell.colSpan || 1;
        const col = columns[index];
        if (col && span === 1) {
          const expected = adminColumnPriorityClass(col.priority);
          const hasSecondary = cell.classList.contains("admin-col-secondary");
          const hasTertiary = cell.classList.contains("admin-col-tertiary");
          const actual = hasSecondary ? "admin-col-secondary" : hasTertiary ? "admin-col-tertiary" : "";
          if (actual !== expected) {
            problems.push(
              `cell ${index} ("${col.key}") has priority class "${actual || "primary"}" but column is "${expected || "primary"}"`,
            );
          }
        }
        index += span;
      }
      if (index !== columns.length) {
        problems.push(`row spans ${index} columns but the table defines ${columns.length}`);
      }
      if (problems.length > 0) {
        const signature = problems.join("|");
        if (!reported.current.has(signature)) {
          reported.current.add(signature);
          console.warn(`AdminDataTable column mismatch: ${problems.join("; ")}`, row);
        }
      }
    });
  });
}

export type AdminDataTableEmptyProps = {
  readonly colSpan: number;
  readonly message: string;
};

export function AdminDataTableEmptyRow({ colSpan, message }: AdminDataTableEmptyProps) {
  return (
    <tr>
      <td colSpan={colSpan} className="text-muted text-center py-4">
        {message}
      </td>
    </tr>
  );
}

export type AdminDataTableCellMetaProps = {
  readonly children: ReactNode;
  /** Breakpoint at which the dedicated column takes over. */
  readonly until?: Exclude<AdminTableColumnPriority, "primary">;
};

/** Secondary line under a primary cell, shown only while its column is hidden. */
export function AdminDataTableCellMeta({
  children,
  until = "secondary",
}: AdminDataTableCellMetaProps) {
  return (
    <span
      className={`admin-table-cell-meta d-block small text-muted ${
        until === "secondary" ? "d-md-none" : "d-lg-none"
      }`}
    >
      {children}
    </span>
  );
}
