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
      ],
    },
    isLoading: false,
    isError: false,
    error: null,
  }),
  useBoardCatalogCandidates: () => ({ data: [], isLoading: false, isError: false, error: null }),
  useBoardCatalogMutations: () => ({
    preview: { isPending: false, isError: false, isSuccess: false, error: null, data: null, mutate },
    importSource: { isPending: false, isError: false, isSuccess: false, error: null, data: null, mutate },
    decide: { isPending: false, isError: false, mutate },
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
  });
});
