import { render as rtlRender, screen, type RenderResult } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { BoardReviewSample } from "../../lib/boardModel";
import { BoardReviewSection } from "./BoardReviewSection";

function render(ui: React.ReactElement): RenderResult {
  return rtlRender(<MemoryRouter initialEntries={["/siu-tin-dei?tab=board&section=review"]}>{ui}</MemoryRouter>);
}

const TASK_ID = "9af74e86da614799864912a3c77d523f";

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
    sample: [] as BoardReviewSample[],
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

describe("BoardReviewSection card lanes", () => {
  it("puts headline, holds, escalations, assisted, sample and market on the full row and status cards on half rows", () => {
    const { container } = render(<BoardReviewSection />);
    expect(container.querySelector("#headline")).toHaveAttribute("data-lane", "main");
    expect(container.querySelector("#holdsDue")).toHaveClass("card");
    expect(container.querySelector("#holdsDue")?.querySelector(".admin-card-title")).toHaveTextContent(
      "Scheduled (veto to stop)",
    );
    expect(screen.queryByRole("heading", { name: "On hold, executing soon" })).not.toBeInTheDocument();
    expect(container.querySelector("#escalations")).toHaveAttribute("data-lane", "main");
    expect(container.querySelector("#assisted")).toHaveAttribute("data-lane", "main");
    expect(container.querySelector("#sample")).toHaveAttribute("data-lane", "main");
    expect(container.querySelector("#market")).toHaveAttribute("data-lane", "main");
    expect(container.querySelector("#breakers")).toHaveAttribute("data-lane", "aside");
    expect(container.querySelector("#configGaps")).toHaveAttribute("data-lane", "aside");
    expect(container.querySelector("#dmarc")).toHaveAttribute("data-lane", "aside");
    expect(container.querySelector("#engineering")).toHaveAttribute("data-lane", "aside");
  });
});

describe("BoardReviewSection sample of what ran", () => {
  it("shows who ran it, the task it belonged to, and the raw details", () => {
    reviewState.review.sample = [
      {
        callId: "call-finish",
        summary: "Finished the task",
        op: "task_finish",
        createdAt: "2026-11-08T01:30:00Z",
        personaId: "content-marketer",
        displayName: "Mei",
        taskId: TASK_ID,
        arguments: JSON.stringify({ status: "review", deliverableType: "json", deliverable: '{"district":"Other"}' }),
        deliverablePreview: '{\n  "district": "Eastern",\n  "organisations": [{ "name_en": "Quarry Bay Park" }]\n}',
        preview: JSON.stringify({ ok: true, status: "review", deliverableKey: "board/executive/staff/t/deliverable.json" }),
        task: {
          taskId: TASK_ID,
          assignee: "content-marketer",
          status: "delivered",
          brief: "Draft the Stanley launch calendar.",
          summary: "Drafted 14 days of Stanley posts.",
        },
      },
      {
        callId: "call-orphan",
        summary: "Finished the task",
        op: "task_finish",
        personaId: "prospector",
        taskId: "missing-task",
        task: null,
      },
    ];
    const { container } = render(<BoardReviewSection />);
    const sample = container.querySelector("#sample");
    expect(sample).toHaveTextContent("Mei");
    expect(sample).toHaveTextContent("Draft the Stanley launch calendar.");
    expect(sample).toHaveTextContent("Result: Drafted 14 days of Stanley posts.");
    expect(sample).toHaveTextContent("delivered");
    expect(screen.getByLabelText(`Task ${TASK_ID}`)).toHaveTextContent(`#${TASK_ID.slice(0, 8)}`);
    const link = screen.getByRole("link", { name: `Open task ${TASK_ID}` });
    expect(link.getAttribute("href")).toContain(`task=${TASK_ID}`);
    expect(link.getAttribute("href")).toContain("section=tasks");
    expect(sample).toHaveTextContent("Task record is no longer available.");
    const details = sample?.querySelectorAll("details") ?? [];
    expect(details).toHaveLength(1);
    expect(details[0]).toHaveTextContent('"deliverable": "{\\"district\\":\\"Other\\"}"');
    expect(details[0]).toHaveTextContent("deliverableKey");
    const item = screen.getAllByText("Finished the task")[0]?.closest("li");
    const shown = item?.querySelector(".board-finish-preview");
    expect(shown).toHaveTextContent("Quarry Bay Park");
    expect(details[0]?.contains(shown ?? null)).toBe(false);
    const text = item?.textContent ?? "";
    expect(text.indexOf("Quarry Bay Park")).toBeGreaterThan(text.indexOf("Finished the task"));
    reviewState.review.sample = [];
  });
});

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
