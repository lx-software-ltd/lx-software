import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminApiError, adminFetchJson } from "../lib/apiAdminClient";
import { formatDateTimeHKT } from "../lib/formatDisplay";
import { lxSoftwareBookFixture } from "../lib/mock/fixtures";
import { LxSoftwarePage } from "./LxSoftwarePage";

vi.mock("../lib/apiAdminClient", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/apiAdminClient")>();
  return { ...actual, adminFetchJson: vi.fn() };
});

const NEXT_SLOT = "2099-01-05T00:30:00.000Z";
const PLAN = {
  planned: 2,
  overdue: 1,
  nextEmptySlot: NEXT_SLOT,
  refreshAt: NEXT_SLOT,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/lx-software"]}>
        <LxSoftwarePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LX Software dashboard", () => {
  beforeEach(() => {
    vi.mocked(adminFetchJson).mockReset();
    vi.mocked(adminFetchJson).mockImplementation(async (path: string) => {
      if (path === "/v1/admin/lx-software") return { data: lxSoftwareBookFixture };
      if (path === "/v1/admin/lx-software/linkedin?view=plan") return PLAN;
      throw new AdminApiError(404, "{}");
    });
  });

  it("puts the LinkedIn plan on the same line as the fiscal year card", async () => {
    renderPage();
    const fiscalYear = await screen.findByLabelText(/LX Software: Fiscal year/);
    const linkedIn = await screen.findByRole("heading", { name: "LinkedIn" });
    const fiscalColumn = fiscalYear.closest("[class*='col-']");
    const linkedInColumn = linkedIn.closest("[class*='col-']");
    expect(fiscalColumn?.parentElement).toBe(linkedInColumn?.parentElement);
    expect(fiscalColumn?.parentElement?.classList.contains("row")).toBe(true);
    const card = linkedIn.closest(".card");
    expect(card).toHaveTextContent("2");
    expect(card).toHaveTextContent("1");
    expect(card).toHaveTextContent(formatDateTimeHKT(NEXT_SLOT));
  });

  it("keeps the LinkedIn plan visible when the statement book fails", async () => {
    vi.mocked(adminFetchJson).mockImplementation(async (path: string) => {
      if (path === "/v1/admin/lx-software/linkedin?view=plan") return PLAN;
      throw new AdminApiError(500, "{}");
    });
    renderPage();
    expect(await screen.findByRole("heading", { name: "LinkedIn" })).toBeTruthy();
    expect(await screen.findByText(formatDateTimeHKT(NEXT_SLOT))).toBeTruthy();
    expect(screen.queryByLabelText(/LX Software: Fiscal year/)).toBeNull();
    expect(screen.getByText(/Records could not be loaded/)).toBeTruthy();
  });
});
