import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TableSortHeaderButton } from "./TableSortHeaderButton";

describe("TableSortHeaderButton", () => {
  it("keeps the sort button for desktop and a static label for phones", () => {
    render(
      <TableSortHeaderButton
        label="Description"
        isActive={false}
        direction={null}
        onClick={vi.fn()}
      />,
    );
    const button = screen.getByRole("button", { name: "Sort by Description" });
    expect(button.className).toContain("d-none");
    expect(button.className).toContain("d-md-inline-block");
    const phoneLabel = screen.getAllByText("Description").find((el) => el.tagName === "SPAN");
    expect(phoneLabel?.className).toContain("d-md-none");
  });
});
