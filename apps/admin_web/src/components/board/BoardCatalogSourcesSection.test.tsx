import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BoardCatalogSourcesSection } from "./BoardCatalogSourcesSection";

const mutate = vi.fn();

vi.mock("../../hooks/useBoardCatalog", () => ({
  useBoardCatalogSources: () => ({
    data: {
      launchTarget: 1000,
      candidateCounts: {},
      sources: [
        {
          id: "lcsd",
          counts: { new: 0, approved: 2, imported: 0, rejected: 0, closed: 0 },
          available: 2,
          job: { phase: "running", action: "preview" },
        },
        {
          id: "edb",
          counts: { new: 0, approved: 1, imported: 0, rejected: 0, closed: 0 },
          available: 1,
        },
        {
          id: "swd",
          counts: { new: 0, approved: 3, imported: 0, rejected: 0, closed: 0 },
          available: 3,
          job: { phase: "running", action: "ingest", offset: 500, remaining: 200 },
        },
      ],
    },
    isLoading: false,
    isError: false,
    error: null,
  }),
  useBoardCatalogCandidates: () => ({
    data: [
      { candidateId: "cand-1", source: "competitor", nameEn: "Example Playhouse", district: "Sha Tin", status: "new" },
    ],
    total: 1,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    isLoading: false,
    isError: false,
    error: null,
  }),
  useBoardCatalogMutations: () => ({
    preview: { isPending: false, isError: false, isSuccess: false, error: null, data: null, mutate },
    importSource: { isPending: false, isError: false, isSuccess: false, error: null, data: null, mutate },
    decide: { isPending: false, isError: false, mutate },
    bulkDecide: { isPending: false, isError: false, isSuccess: false, error: null, data: null, mutate },
    runDiscovery: { isPending: false, isError: false, isSuccess: false, error: null, data: null, mutate },
  }),
}));

describe("BoardCatalogSourcesSection", () => {
  it("disables Preview and Import while a source job is running", () => {
    render(<BoardCatalogSourcesSection />);
    expect(screen.getByText("Preview running…")).toBeInTheDocument();
    const previewButtons = screen.getAllByRole("button", { name: "Preview" });
    const importButtons = screen.getAllByRole("button", { name: "Import" });
    expect(previewButtons[0]).toBeDisabled();
    expect(importButtons[0]).toBeDisabled();
    expect(previewButtons[1]).toBeEnabled();
    expect(importButtons[1]).toBeEnabled();
    expect(screen.getByText("Ingest running 500 done, 200 left…")).toBeInTheDocument();
    expect(previewButtons[2]).toBeDisabled();
    expect(importButtons[2]).toBeDisabled();
  });

  it("lists filtered candidates and a leftover-competitor reject action", () => {
    render(<BoardCatalogSourcesSection />);
    expect(screen.getByLabelText("Source")).toBeInTheDocument();
    expect(screen.getByLabelText("District")).toBeInTheDocument();
    expect(screen.getByText("Example Playhouse")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve Example Playhouse" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject leftover competitors" })).toBeInTheDocument();
  });
});
