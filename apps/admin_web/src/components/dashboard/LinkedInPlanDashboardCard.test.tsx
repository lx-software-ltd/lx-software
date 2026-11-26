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

const NEXT_SLOT = "2099-01-05T00:30:00.000Z";

describe("LinkedIn plan dashboard card", () => {
  beforeEach(() => {
    vi.mocked(adminFetchJson).mockReset();
  });

  it("shows upcoming posts, overdue posts, and the first empty slot", async () => {
    vi.mocked(adminFetchJson).mockResolvedValue({
      planned: 2,
      overdue: 1,
      nextEmptySlot: NEXT_SLOT,
      refreshAt: NEXT_SLOT,
    });
    renderCard();
    expect(screen.getByText("Loading LinkedIn plan…")).toBeTruthy();
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText("1")).toBeTruthy();
    expect(screen.getByText(formatDateTimeHKT(NEXT_SLOT))).toBeTruthy();
    expect(screen.getByText(/their slot has not arrived/)).toBeTruthy();
    expect(vi.mocked(adminFetchJson)).toHaveBeenCalledWith("/v1/admin/lx-software/linkedin?view=plan");
  });

  it("hides a slot that has already started", async () => {
    vi.mocked(adminFetchJson).mockResolvedValue({
      planned: 0,
      overdue: 1,
      nextEmptySlot: "2020-01-01T00:30:00.000Z",
      refreshAt: "2020-01-01T00:30:00.000Z",
    });
    renderCard();
    expect(await screen.findByText("None in the next few months")).toBeTruthy();
    expect(screen.queryByText(formatDateTimeHKT("2020-01-01T00:30:00.000Z"))).toBeNull();
  });

  it("says when the schedule has no open slot", async () => {
    vi.mocked(adminFetchJson).mockResolvedValue({
      planned: 0,
      overdue: 0,
      nextEmptySlot: null,
      refreshAt: null,
    });
    renderCard();
    expect(await screen.findByText("None in the next few months")).toBeTruthy();
  });

  it("shows an error when the plan cannot be loaded", async () => {
    vi.mocked(adminFetchJson).mockRejectedValue(new AdminApiError(500, "{}"));
    renderCard();
    expect(await screen.findByText("Could not load the LinkedIn plan.")).toBeTruthy();
  });
});
