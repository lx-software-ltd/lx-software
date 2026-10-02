import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

function Boom(): never {
  throw new Error("chunk failed");
}

describe("RouteErrorBoundary", () => {
  it("shows a reload alert when a lazy page throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <RouteErrorBoundary>
        <Boom />
      </RouteErrorBoundary>,
    );
    expect(screen.getByRole("alert").textContent).toContain("This page failed to load.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
  });
});
