import { Component, type ReactNode } from "react";

type RouteErrorBoundaryProps = {
  readonly children: ReactNode;
};

type RouteErrorBoundaryState = {
  readonly hasError: boolean;
};

/** Catches a failed lazy route so the shell can stay up and the user can reload. */
export class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): RouteErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-3" role="alert">
          <p className="mb-2">This page failed to load.</p>
          <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
