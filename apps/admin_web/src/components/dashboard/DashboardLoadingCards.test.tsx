import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DashboardApiHealthCard } from "./DashboardApiHealthCard";
import { DashboardSessionCard } from "./DashboardSessionCard";

describe("dashboard loading cards", () => {
  it("replaces the API health card with a bao row while the check is in flight", () => {
    render(<DashboardApiHealthCard isLoading isError={false} status={undefined} />);
    const row = screen.getByRole("status");
    expect(row).toHaveTextContent("Checking /health…");
    expect(row.querySelector(".admin-bao")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "API health" })).toBeNull();
  });

  it("keeps the API health card once the check finishes", () => {
    render(<DashboardApiHealthCard isLoading={false} isError={false} status="ok" />);
    expect(screen.getByRole("heading", { name: "API health" })).toBeTruthy();
    expect(screen.getByText("ok")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("replaces the session card with a bao row while the profile loads", () => {
    render(
      <DashboardSessionCard isLoading isError={false} sub={undefined} email={undefined} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading profile…");
    expect(screen.queryByRole("heading", { name: "Session" })).toBeNull();
  });

  it("keeps the session card once the profile is known", () => {
    render(
      <DashboardSessionCard
        isLoading={false}
        isError={false}
        sub="mock-admin"
        email="mock.admin@example.com"
      />,
    );
    expect(screen.getByRole("heading", { name: "Session" })).toBeTruthy();
    expect(screen.getByText("mock.admin@example.com")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
