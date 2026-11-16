import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminApiError, adminFetchJson } from "../../lib/apiAdminClient";
import { formatDateTimeHKT } from "../../lib/formatDisplay";
import { LinkedInPlanDashboardCard } from "./LinkedInPlanDashboardCard";

vi.mock("../../lib/apiAdminClient", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/apiAdminClient")>();
  return { ...actual, adminFetchJson: vi.fn() };
});

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <LinkedInPlanDashboardCard />
    </QueryClientProvider>,
  );
}

const NEXT_SLOT = "2026-11-17T00:30:00.000Z";

describe("LinkedIn plan dashboard card", () => {
  beforeEach(() => {
    vi.mocked(adminFetchJson).mockReset();
  });

  it("shows how many posts are planned and the first empty slot", async () => {
    vi.mocked(adminFetchJson).mockResolvedValue({
      counts: { approved: 2 },
      nextSlots: [NEXT_SLOT, "2026-11-19T00:30:00.000Z"],
    });
    renderCard();
    expect(screen.getByText("Loading LinkedIn plan…")).toBeTruthy();
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText(formatDateTimeHKT(NEXT_SLOT))).toBeTruthy();
    expect(screen.getByText(/approved and waiting/)).toBeTruthy();
    expect(screen.queryByText(formatDateTimeHKT("2026-11-19T00:30:00.000Z"))).toBeNull();
  });

  it("says when the schedule has no open slot", async () => {
    vi.mocked(adminFetchJson).mockResolvedValue({ counts: { approved: 0 }, nextSlots: [] });
    renderCard();
    expect(await screen.findByText("0")).toBeTruthy();
    expect(screen.getByText("None in the next few months")).toBeTruthy();
  });

  it("shows an error when the overview cannot be loaded", async () => {
    vi.mocked(adminFetchJson).mockRejectedValue(new AdminApiError(500, "{}"));
    renderCard();
    expect(await screen.findByText("Could not load the LinkedIn plan.")).toBeTruthy();
  });
});
