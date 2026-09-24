export type AdminTableColumnPriority = "primary" | "secondary" | "tertiary";

export const ADMIN_COL_OPS_CLASS = "admin-col-ops";

export const ADMIN_COL_PRIORITY_CLASS: Record<AdminTableColumnPriority, string> = {
  primary: "",
  secondary: "admin-col-secondary",
  tertiary: "admin-col-tertiary",
};

/** CSS class that hides a table column below `md` (`secondary`) or `lg` (`tertiary`). */
export function adminColumnPriorityClass(
  priority: AdminTableColumnPriority = "primary",
): string {
  return ADMIN_COL_PRIORITY_CLASS[priority];
}

/**
 * Class for a column definition. The kebab column (`key: "ops"`) stays in the
 * body on phones; its header is omitted so the identifying header can span
 * the table (see `.admin-col-ops` in tables.css).
 */
export function adminColumnClass(column: {
  readonly key: string;
  readonly priority?: AdminTableColumnPriority;
}): string {
  if (column.key === "ops") return ADMIN_COL_OPS_CLASS;
  return adminColumnPriorityClass(column.priority);
}
