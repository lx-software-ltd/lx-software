import { Suspense, type ReactNode } from "react";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { AdminWaitRow } from "./ui";

export function LazyPage({ children }: { readonly children: ReactNode }) {
  return (
    <RouteErrorBoundary>
      <Suspense
        fallback={
          <div className="p-3">
            <AdminWaitRow>Loading…</AdminWaitRow>
          </div>
        }
      >
        {children}
      </Suspense>
    </RouteErrorBoundary>
  );
}
