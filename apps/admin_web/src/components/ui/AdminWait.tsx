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
          d="M16 2.4c-.9 3.6-3.2 5.4-5.6 6.3C6.4 10 3.4 13.8 3.4 18.6 3.4 25.2 8.8 29.2 16 29.2s12.6-4 12.6-10.6c0-4.8-3-8.6-7-9.9-2.4-.9-4.7-2.7-5.6-6.3z"
        />
        <g
          fill="none"
          stroke="#042f2e"
          strokeOpacity="0.55"
          strokeWidth="1.45"
          strokeLinecap="round"
        >
          <path d="M16 6.2v7.6" />
          <path d="M16 9.4c-2.7 1.6-5.6 2.1-8.4 1.6" />
          <path d="M16 9.4c2.7 1.6 5.6 2.1 8.4 1.6" />
          <path d="M16 13.4c-3.7 2.1-7.2 2.5-10.4 1.6" />
          <path d="M16 13.4c3.7 2.1 7.2 2.5 10.4 1.6" />
        </g>
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
