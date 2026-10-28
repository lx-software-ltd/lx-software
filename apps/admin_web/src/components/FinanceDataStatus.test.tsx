import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FinanceDataLoadOrError } from "./FinanceDataStatus";

describe("FinanceDataLoadOrError", () => {
  it("shows the loading sentence beside a bao on the page background", () => {
    render(<FinanceDataLoadOrError isLoading isError={false} />);
    const row = screen.getByRole("status");
    expect(row).toHaveTextContent("Loading finance data…");
    expect(row).toHaveClass("admin-wait");
    expect(row.querySelector(".admin-bao")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the danger alert when the query fails", () => {
    render(
      <FinanceDataLoadOrError
        isLoading={false}
        isError
        loadErrorMessage="Could not load finance data"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load finance data");
    expect(screen.queryByRole("status")).toBeNull();
  });
});
