import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { boardOverviewFixture } from "../../lib/mock/fixtures";
import { BoardSettingsCard } from "./BoardSettingsCard";

const members = boardOverviewFixture.members;

describe("BoardSettingsCard", () => {
  it("exposes concurrent tasks and staff daily budget under Staff and daily review", () => {
    const onSave = vi.fn();
    render(
      <BoardSettingsCard
        overview={boardOverviewFixture}
        members={members}
        isSaving={false}
        onSave={onSave}
        onRefreshRepo={vi.fn()}
        isRefreshingRepo={false}
      />,
    );

    const target = screen.getByLabelText("Launch listing target");
    expect(target).toHaveValue(null);
    expect(target).toHaveAttribute("placeholder", "1000");
    fireEvent.change(target, { target: { value: "1200" } });
    expect(target).toHaveValue(1200);
    fireEvent.change(target, { target: { value: "" } });
    expect(target).toHaveValue(null);

    const concurrent = screen.getByLabelText("Concurrent tasks");
    expect(concurrent).toHaveValue(6);
    fireEvent.change(concurrent, { target: { value: "8" } });
    expect(concurrent).toHaveValue(8);

    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        staff: expect.objectContaining({ enabled: true, maxRunningTasks: 8, dailyBudgetUsd: 20 }),
      }),
    );
  });
});
