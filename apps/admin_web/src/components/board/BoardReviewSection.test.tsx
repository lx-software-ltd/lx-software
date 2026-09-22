import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BoardReviewSection } from "./BoardReviewSection";

const reviewState = vi.hoisted(() => ({
  review: {
    date: "2026-09-16",
    narrative: "Staging is behind main.",
    headline: {
      tasks: { delivered: 0, running: 0, blocked: 0 },
      messagesByChannel: {},
      holds: { executed: 0, vetoed: 0 },
      spend: { boardUsd: 0, staffUsd: 0, budgetUsd: 20 },
      catalog: { importedDistricts: 6, completeDistricts: 2, nextDistrict: "Islands", revalidateExhausted: 1 },
    },
    holdsDue: [],
    escalations: [],
    sample: [],
    breakers: [],
    suggestions: [],
    assisted: [],
  },
  staging: {
    status: "diverged",
    behindBy: 3,
    aheadBy: 1,
    canPromote: false,
    commits: [{ sha: "a1b2c3d4", message: "board: #42 add booking" }],
  },
  syncMutate: vi.fn(),
  promoteMutate: vi.fn(),
}));

vi.mock("../../hooks/useBoardReview", () => ({
  useBoardReview: () => ({
    review: reviewState.review,
    lessons: [],
    breakers: [],
    ramp: [],
    staging: reviewState.staging,
    isLoading: false,
    isError: false,
    error: null,
    markWrong: { isPending: false, isError: false, error: null, mutate: vi.fn() },
    confirmLesson: { isPending: false, mutate: vi.fn() },
    dismissLesson: { isPending: false, mutate: vi.fn() },
    resetBreaker: { isPending: false, mutate: vi.fn() },
    promote: { isPending: false, mutate: vi.fn() },
    promoteStaging: {
      isPending: false,
      isSuccess: false,
      isError: false,
      error: null,
      mutate: reviewState.promoteMutate,
    },
    syncStaging: {
      isPending: false,
      isSuccess: false,
      isError: false,
      error: null,
      data: undefined,
      mutate: reviewState.syncMutate,
    },
  }),
}));

vi.mock("../../hooks/useBoardHolds", () => ({
  useBoardHolds: () => ({
    holds: [],
    isLoading: false,
    veto: { isPending: false, error: null, mutate: vi.fn() },
    vetoClass: { isPending: false, error: null, mutate: vi.fn() },
  }),
}));

vi.mock("../../hooks/useBoardContent", () => ({
  useBoardContent: () => ({
    update: { isPending: false, mutate: vi.fn() },
  }),
}));

describe("BoardReviewSection staging sync", () => {
  it("shows Sync from main when staging is behind and keeps Promote disabled", () => {
    reviewState.syncMutate.mockClear();
    reviewState.promoteMutate.mockClear();
    reviewState.staging = {
      status: "diverged",
      behindBy: 3,
      aheadBy: 1,
      canPromote: false,
      commits: [{ sha: "a1b2c3d4", message: "board: #42 add booking" }],
    };
    render(<BoardReviewSection />);
    const sync = screen.getByRole("button", { name: "Sync from main" });
    const promote = screen.getByRole("button", { name: "Promote" });
    expect(sync).toBeEnabled();
    expect(promote).toBeDisabled();
    expect(screen.getByText(/3 commit\(s\) behind main/)).toBeInTheDocument();
    expect(screen.getByText(/Catalog:/)).toBeInTheDocument();
    expect(screen.getByText(/next Islands/)).toBeInTheDocument();
    expect(screen.getByText(/1 automatic retries exhausted/)).toBeInTheDocument();
    sync.click();
    expect(reviewState.syncMutate).toHaveBeenCalledTimes(1);
  });

  it("offers Sync from main when the only commits ahead are sync merges", () => {
    reviewState.syncMutate.mockClear();
    reviewState.staging = {
      status: "ahead",
      behindBy: 0,
      aheadBy: 6,
      canPromote: false,
      syncOnly: true,
      commits: [{ sha: "abc12345", message: "board: sync staging with main" }],
    };
    render(<BoardReviewSection />);
    expect(screen.getByRole("button", { name: "Sync from main" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Promote" })).toBeDisabled();
    expect(screen.getByText(/Only sync merges are ahead of main/)).toBeInTheDocument();
  });

  it("hides Sync from main when staging is current", () => {
    reviewState.staging = {
      status: "ahead",
      behindBy: 0,
      aheadBy: 1,
      canPromote: true,
      commits: [{ sha: "a1b2c3d4", message: "board: #42 add booking" }],
    };
    render(<BoardReviewSection />);
    expect(screen.queryByRole("button", { name: "Sync from main" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Promote" })).toBeEnabled();
  });
});
