import type { ReactNode } from "react";

export type AdminBaoProps = {
  /** `sm` is the inline wheel (no float). The default is the page-level mark. */
  readonly size?: "md" | "sm";
};

/** Char siu bao used as the console's wait mark. Decorative; the sentence carries the status. */
export function AdminBao({ size = "md" }: AdminBaoProps) {
  return (
    <span className={size === "sm" ? "admin-bao admin-bao-sm" : "admin-bao"} aria-hidden="true">
      <svg className="admin-bao-glyph" viewBox="0 0 32 32">
        <path
          fill="currentColor"
          d="M16 5c-1.4 2.6-3.6 3.8-6.2 4.6C6 11 3.5 14.6 3.5 19.2 3.5 25 8.8 28.5 16 28.5S28.5 25 28.5 19.2C28.5 14.6 26 11 22.2 9.6 19.6 8.8 17.4 7.6 16 5z"
        />
        <path
          fill="none"
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          opacity="0.45"
          d="M16 7.5v7.5M16 11c-3 1.6-6 1.8-9 .6M16 11c3 1.6 6 1.8 9 .6M16 15c-4.2 2-8 2.2-11.2.8M16 15c4.2 2 8 2.2 11.2.8"
        />
      </svg>
    </span>
  );
}

/** Loading sentence on the page background, with the bao on the left. */
export function AdminWaitRow({ children }: { readonly children: ReactNode }) {
  return (
    <p className="admin-wait" role="status">
      <AdminBao />
      <span>{children}</span>
    </p>
  );
}
