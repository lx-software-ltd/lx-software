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
