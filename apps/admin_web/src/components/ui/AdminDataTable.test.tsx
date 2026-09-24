import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

  it("exposes a phone sort control when sort is provided", () => {
    const onChange = vi.fn();
    render(
      <AdminDataTable
        columns={[{ key: "name", header: "Name" }]}
        filterValue=""
        onFilterChange={() => undefined}
        sort={{
          options: [{ key: "name", label: "Name" }],
          sortKey: "name",
          direction: "asc",
          onChange,
        }}
      >
        <tr>
          <AdminCell column="name">Alpha</AdminCell>
        </tr>
      </AdminDataTable>,
    );
    expect(screen.getByLabelText("Sort by")).toBeTruthy();
  });

  it("keeps the phone sort control when the card and text filter are omitted", () => {
    render(
      <AdminDataTable
        bare
        columns={[{ key: "name", header: "Name" }]}
        sort={{
          options: [{ key: "name", label: "Name" }],
          sortKey: null,
          direction: "asc",
          onChange: () => undefined,
        }}
      >
        <tr>
          <AdminCell column="name">Alpha</AdminCell>
        </tr>
      </AdminDataTable>,
    );
    expect(screen.getByLabelText("Sort by")).toBeTruthy();
    expect(screen.queryByPlaceholderText("Filter records…")).toBeNull();
  });
});
