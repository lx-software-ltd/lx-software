import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { financeFixture } from "../lib/mock/fixtures";
import { LEDGER_RELATED_HOUSE_OPTIONS } from "../lib/houses";
import { FinanceInvestmentsPanel } from "./FinanceInvestmentsPanel";

function renderPanel(initialEntry = "/"): ReturnType<typeof render> {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const tree: ReactElement = (
    <MemoryRouter initialEntries={[initialEntry]}>
      <QueryClientProvider client={client}>
        <FinanceInvestmentsPanel
          records={financeFixture.investmentRecords}
          onPatch={vi.fn()}
          relatedHouseOptions={LEDGER_RELATED_HOUSE_OPTIONS}
        />
      </QueryClientProvider>
    </MemoryRouter>
  );
  return render(tree);
}

describe("FinanceInvestmentsPanel columns", () => {
  it("labels the principal column Principal and puts a currency converter on that total", () => {
    renderPanel();

    expect(screen.getByRole("columnheader", { name: /Principal/ })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /Current Value/ })).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: /Sort by Currency/ })).toBeNull();

    expect(screen.getByLabelText("Principal total display currency")).toBeTruthy();
    expect(screen.getByLabelText("Current value total display currency")).toBeTruthy();
  });

  it("shows current value in the row editor for every category", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "New investment" }));
    const createField = screen.getByLabelText("Current value");
    expect(createField).toBeTruthy();
    expect((createField as HTMLInputElement).required).toBe(true);
  });

  it("fills current value when editing real estate and keeps the field for other categories", () => {
    const { unmount } = renderPanel("/?investment=iv-1");
    expect((screen.getByLabelText("Current value") as HTMLInputElement).value).toBe("512000");
    unmount();

    renderPanel("/?investment=iv-2");
    expect(screen.getByLabelText("Current value")).toBeTruthy();
  });
});
