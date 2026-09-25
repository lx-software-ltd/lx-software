import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardOverview } from "../../lib/boardModel";
import { BoardHeaderStrip } from "./BoardHeaderStrip";

const overview = {
  openActionCount: 2,
  runningMeeting: null,
  latestMeeting: {
    meetingId: "mtg-3",
    mode: "standup",
    headline: "Ship the provider onboarding form",
    actionCount: 4,
    createdAt: "2026-09-16T02:00:00Z",
    usage: { cost: 0.41 },
  },
  usageToday: { cost: 0.41, budgetUsd: 15 },
} as BoardOverview;

describe("BoardHeaderStrip", () => {
  it("uses the dashboard KPI row for meeting, actions, and spend", () => {
    const { container } = render(
      <BoardHeaderStrip
        overview={overview}
        onRunStandup={vi.fn()}
        onPlanDeepDive={vi.fn()}
        onOpenMeeting={vi.fn()}
        isStarting={false}
      />,
    );
    const row = container.querySelector(".admin-kpi-row");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("Latest meeting");
    expect(row).toHaveTextContent("Open actions");
    expect(row).toHaveTextContent("2");
    expect(row).toHaveTextContent("Spend today");
    expect(row).toHaveTextContent("USD 0.41 / USD 15.00");
    expect(screen.getByRole("button", { name: "Read the minutes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run stand-up" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deep dive…" })).toBeInTheDocument();
    expect(container.querySelector(".card")).toBeNull();
  });
});
