import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LazyPage } from "./LazyPage";

function Stall(): never {
  throw new Promise<void>(() => undefined);
}

describe("LazyPage", () => {
  it("shows a bao row while the route is still downloading", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <LazyPage>
        <Stall />
      </LazyPage>,
    );
    const row = screen.getByRole("status");
    expect(row).toHaveTextContent("Loading…");
    expect(row.querySelector(".admin-bao")).toBeTruthy();
  });
});
