import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AdminCell, AdminDataTable } from "./AdminDataTable";

describe("AdminDataTable", () => {
  it("applies the column priority class from AdminCell", () => {
    render(
      <AdminDataTable
        columns={[
          { key: "name", header: "Name" },
          { key: "extra", header: "Extra", priority: "secondary" },
        ]}
        filterValue=""
        onFilterChange={() => undefined}
      >
        <tr>
          <AdminCell column="name">Alpha</AdminCell>
          <AdminCell column="extra">Hidden on phones</AdminCell>
        </tr>
      </AdminDataTable>,
    );
    const extra = screen.getByText("Hidden on phones");
    expect(extra.className).toContain("admin-col-secondary");
    expect(screen.getByText("Alpha").className).not.toContain("admin-col-");
  });

  it("marks the operations column on the header and body cells", () => {
    render(
      <AdminDataTable
        columns={[
          { key: "name", header: "Name" },
          { key: "ops", header: <span className="visually-hidden">Operations</span> },
        ]}
        filterValue=""
        onFilterChange={() => undefined}
      >
        <tr>
          <AdminCell column="name">Alpha</AdminCell>
          <AdminCell column="ops">Menu</AdminCell>
        </tr>
      </AdminDataTable>,
    );
    expect(screen.getByRole("columnheader", { name: "Operations" }).className).toContain(
      "admin-col-ops",
    );
    expect(screen.getByText("Menu").className).toContain("admin-col-ops");
  });

  it("does not render a phone sort control", () => {
    render(
      <AdminDataTable
        columns={[{ key: "name", header: "Name" }]}
        filterValue=""
        onFilterChange={() => undefined}
      >
        <tr>
          <AdminCell column="name">Alpha</AdminCell>
        </tr>
      </AdminDataTable>,
    );
    expect(screen.queryByLabelText("Sort by")).toBeNull();
  });

  it("omits the card and text filter when bare", () => {
    render(
      <AdminDataTable bare columns={[{ key: "name", header: "Name" }]}>
        <tr>
          <AdminCell column="name">Alpha</AdminCell>
        </tr>
      </AdminDataTable>,
    );
    expect(screen.queryByLabelText("Sort by")).toBeNull();
    expect(screen.queryByPlaceholderText("Filter records…")).toBeNull();
  });
});
