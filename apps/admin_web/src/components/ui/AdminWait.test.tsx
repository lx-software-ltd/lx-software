import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AdminBao, AdminWaitRow } from "./AdminWait";

describe("AdminWait", () => {
  it("puts a full-size bao on the left of the status sentence", () => {
    render(<AdminWaitRow>Completing sign-in…</AdminWaitRow>);
    const row = screen.getByRole("status");
    expect(row).toHaveTextContent("Completing sign-in…");
    expect(row).toHaveClass("admin-wait");
    const bao = row.querySelector(".admin-bao");
    expect(bao).toBeTruthy();
    expect(bao).not.toHaveClass("admin-bao-sm");
    expect(bao?.getAttribute("aria-hidden")).toBe("true");
    expect(bao?.querySelector("svg.admin-bao-glyph")).toBeTruthy();
  });

  it("uses the small bao for an inline wheel", () => {
    const { container } = render(<AdminBao size="sm" />);
    const bao = container.querySelector(".admin-bao");
    expect(bao).toHaveClass("admin-bao-sm");
  });
});
