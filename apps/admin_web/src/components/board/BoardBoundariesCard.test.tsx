import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_BOARD_BOUNDARIES, type BoardBoundaries } from "../../lib/boardModel";
import { BoardBoundariesCard } from "./BoardBoundariesCard";

describe("BoardBoundariesCard", () => {
  it("resyncs the draft when query data changes", () => {
    const onSave = vi.fn();
    const first: BoardBoundaries = {
      ...DEFAULT_BOARD_BOUNDARIES,
      reply: { ...DEFAULT_BOARD_BOUNDARIES.reply, tone: "First tone" },
    };
    const { rerender } = render(
      <BoardBoundariesCard boundaries={first} version={1} isSaving={false} onSave={onSave} />
    );
    expect(screen.getByLabelText("Tone")).toHaveValue("First tone");
    const second: BoardBoundaries = {
      ...DEFAULT_BOARD_BOUNDARIES,
      reply: { ...DEFAULT_BOARD_BOUNDARIES.reply, tone: "Updated from query" },
    };
    rerender(<BoardBoundariesCard boundaries={second} version={2} isSaving={false} onSave={onSave} />);
    expect(screen.getByLabelText("Tone")).toHaveValue("Updated from query");
  });
});
