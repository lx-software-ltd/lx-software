import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardProgressSnapshot } from "../../lib/boardModel";
import { BoardProgressSection } from "./BoardProgressSection";

const snap: BoardProgressSnapshot = {
  fetchedAt: "2026-09-13T14:00:00Z",
  listings: {
    activities: 12,
    providers: 6,
    stores: 4,
    completenessAvg: 0.45,
    byDistrict: [
      { label: "Sha Tin", activities: 12, providers: 4, stores: 4, completenessAvg: 0.8 },
      { label: "Tai Po", activities: 0, providers: 2, stores: 0, completenessAvg: 0.1 },
    ],
    funnel7d: { listingViews: 20, leads: 3, bookings: 1 },
    gaps: [{ kind: "district", label: "Tai Po", detail: "0 listings · completeness 10%" }],
  },
  signings: {
    count: 2,
    byOnboardingStep: { photos: 1, live: 1 },
    bySubscription: { incomplete: 1, active: 1 },
    stalled: [{ id: "org-1", name: "Sha Tin Playhouse", step: "photos", status: "incomplete", daysSinceLastEdit: 18 }],
  },
  partnerships: {
    byStage: { qualified: 1, contacted: 1, listed: 0 },
    qualifiedThisWeek: 1,
    weeklyTarget: 50,
    needsContact: 1,
    stalled: [{ id: "p-contact", name: "Tai Po Hall", stage: "contacted", district: "Tai Po" }],
  },
  content: {
    byStatus: { drafted: 1, scheduled: 1 },
    scheduledNext7: 1,
    emptyChannels: ["instagram"],
    stalledDrafts: [{ id: "cnt-old", channel: "facebook", status: "drafted", slotAt: "2026-09-08T00:00:00Z", title: "Old draft" }],
    horizonDays: 7,
  },
  bottlenecks: [
    { id: "listings-gap", area: "listings", severity: "warning", summary: "Listing gap in Tai Po: 0 listings · completeness 10%", section: "progress" },
    { id: "partnerships-target", area: "partnerships", severity: "danger", summary: "Partnership pipeline 1 this week vs target 50", section: "pipeline" },
  ],
};

vi.mock("../../hooks/useBoardProgress", () => ({
  useBoardProgress: () => ({ data: snap, isLoading: false, isError: false, error: null }),
}));

describe("BoardProgressSection", () => {
  it("shows catalog, signings, stalled outreach and bottlenecks", () => {
    render(<BoardProgressSection />);
    expect(screen.getByRole("heading", { name: "Progress" })).toBeInTheDocument();
    expect(screen.getByText("Live listings")).toBeInTheDocument();
    expect(screen.getByText("Sha Tin Playhouse")).toBeInTheDocument();
    expect(screen.getByText("Tai Po Hall")).toBeInTheDocument();
    expect(screen.getByText("Old draft")).toBeInTheDocument();
    expect(screen.getByText("1 / 50")).toBeInTheDocument();
    expect(screen.getByText(/Listing gap in Tai Po/i)).toBeInTheDocument();
  });
});
