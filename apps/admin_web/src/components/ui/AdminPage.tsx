import type { ReactNode } from "react";
import { AdminPageHeader } from "./AdminPageHeader";

export type AdminPageProps = {
  readonly title: string;
  readonly help?: ReactNode;
  readonly actions?: ReactNode;
  readonly className?: string;
  readonly children: ReactNode;
};

/**
 * The only page frame: title, optional help, optional actions, then the body.
 * Section tabs, when a page has them, are the first thing in the body.
 */
export function AdminPage({ title, help, actions, className, children }: AdminPageProps) {
  return (
    <div className={className ? `admin-page ${className}` : "admin-page"}>
      <AdminPageHeader title={title} help={help} actions={actions} />
      {children}
    </div>
  );
}
