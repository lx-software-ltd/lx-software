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
    hasPhotoAvg: 0.2,
    hasPriceAvg: 0.4,
    hasScheduleAvg: 0.3,
    hasGeoAvg: 0.9,
    byDistrict: [
      { label: "Sha Tin", activities: 12, providers: 4, stores: 4, completenessAvg: 0.8, hasPhotoAvg: 0.5, hasPriceAvg: 0.8, hasScheduleAvg: 0.8, hasGeoAvg: 1 },
      { label: "Tai Po", activities: 0, providers: 2, stores: 0, completenessAvg: 0.1, hasPhotoAvg: 0, hasPriceAvg: 0, hasScheduleAvg: 0, hasGeoAvg: 0.4 },
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

vi.mock("../../hooks/useBoardCatalog", () => ({
  useBoardCatalogSources: () => ({
    data: { sources: [], launchTarget: 1000, candidateCounts: {} },
    isLoading: false,
    isError: false,
    error: null,
  }),
  useBoardCatalogCandidates: () => ({ data: [], isLoading: false, isError: false, error: null }),
  useBoardCatalogMutations: () => ({
    preview: { isPending: false, isError: false, error: null, mutate: vi.fn() },
    importSource: { isPending: false, isError: false, error: null, mutate: vi.fn() },
    decide: { isPending: false, isError: false, mutate: vi.fn() },
    runDiscovery: { isPending: false, mutate: vi.fn() },
  }),
}));

describe("BoardProgressSection", () => {
  it("shows catalog, signings, stalled outreach and bottlenecks", () => {
    render(<BoardProgressSection />);
    expect(screen.getByRole("heading", { name: "Progress" })).toBeInTheDocument();
    expect(screen.getByText("Bulk catalog sources")).toBeInTheDocument();
    expect(screen.getByText("Live listings")).toBeInTheDocument();
    expect(screen.getByText("Sha Tin Playhouse")).toBeInTheDocument();
    expect(screen.getByText("Tai Po Hall")).toBeInTheDocument();
    expect(screen.getByText("Old draft")).toBeInTheDocument();
    expect(screen.getByText("1 / 50")).toBeInTheDocument();
    expect(screen.getByText(/Listing gap in Tai Po/i)).toBeInTheDocument();
    expect(screen.getByText("Photo")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("Hours")).toBeInTheDocument();
    expect(screen.getByText("Geo")).toBeInTheDocument();
  });
});
