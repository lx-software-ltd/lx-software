export type AdminNavItem = {
  readonly to: string;
  readonly label: string;
  readonly icon: string;
  readonly end?: boolean;
};

export const ADMIN_NAV_GROUPS: readonly (readonly AdminNavItem[])[] = [
  [{ to: "/", label: "Dashboard", icon: "bi-grid", end: true }],
  [
    { to: "/finance", label: "House Finance", icon: "bi-house" },
    { to: "/lx-software", label: "LX Software", icon: "bi-building" },
    { to: "/siu-tin-dei", label: "Siu Tin Dei", icon: "bi-compass" },
  ],
  [
    { to: "/banking", label: "Banking", icon: "bi-bank" },
    { to: "/assets", label: "Assets", icon: "bi-folder" },
  ],
];

export type AdminCommandItem = {
  readonly id: string;
  readonly label: string;
  readonly hint: string;
  readonly to: string;
};

const FINANCE_SECTIONS: readonly { readonly id: string; readonly label: string }[] = [
  { id: "hillmarton", label: "32 Hillmarton" },
  { id: "morrison", label: "The Morrison" },
  { id: "investments", label: "Investments" },
  { id: "savings", label: "Savings" },
  { id: "pension", label: "Pension" },
  { id: "income", label: "Income" },
  { id: "expenses", label: "Expenses" },
  { id: "allocations", label: "Allocations" },
  { id: "accounts", label: "Accounts" },
  { id: "liabilities", label: "Liabilities" },
];

const BOOK_SECTIONS: readonly { readonly id: string; readonly label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "expenses", label: "Expenses" },
  { id: "gains", label: "Gains" },
];

const BOARD_SECTIONS: readonly { readonly id: string; readonly label: string }[] = [
  { id: "review", label: "Daily review" },
  { id: "progress", label: "Progress" },
  { id: "market", label: "Market" },
  { id: "pipeline", label: "Pipeline" },
  { id: "content", label: "Content" },
  { id: "actions", label: "Next actions" },
  { id: "staff", label: "Staff" },
  { id: "tasks", label: "Tasks" },
  { id: "approvals", label: "Approvals" },
  { id: "mail", label: "Mail" },
  { id: "receivables", label: "Receivables" },
  { id: "meetings", label: "Meetings" },
  { id: "members", label: "Board members" },
  { id: "brief", label: "Charter & brief" },
  { id: "settings", label: "Settings" },
];

/** Destinations for the command palette. Section badges stay on the rail itself. */
export function adminCommandItems(): readonly AdminCommandItem[] {
  const pages: AdminCommandItem[] = ADMIN_NAV_GROUPS.flat().map((item) => ({
    id: `page:${item.to}`,
    label: item.label,
    hint: "Page",
    to: item.to,
  }));
  const finance = FINANCE_SECTIONS.map((section) => ({
    id: `finance:${section.id}`,
    label: section.label,
    hint: "House Finance",
    to: `/finance?tab=${section.id}`,
  }));
  const lx = BOOK_SECTIONS.map((section) => ({
    id: `lx:${section.id}`,
    label: section.label,
    hint: "LX Software",
    to: `/lx-software?tab=${section.id}`,
  }));
  const book = BOOK_SECTIONS.map((section) => ({
    id: `siu:${section.id}`,
    label: section.label,
    hint: "Siu Tin Dei",
    to: `/siu-tin-dei?tab=${section.id}`,
  }));
  const board = BOARD_SECTIONS.map((section) => ({
    id: `board:${section.id}`,
    label: section.label,
    hint: "Executive Board",
    to: `/siu-tin-dei?tab=board&section=${section.id}`,
  }));
  return [...pages, ...finance, ...lx, ...book, ...board];
}
