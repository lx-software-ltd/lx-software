import { Suspense, type ReactNode } from "react";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

export function LazyPage({ children }: { readonly children: ReactNode }) {
  return (
    <RouteErrorBoundary>
      <Suspense fallback={<p className="text-muted small p-3 mb-0">Loading…</p>}>{children}</Suspense>
    </RouteErrorBoundary>
  );
}
