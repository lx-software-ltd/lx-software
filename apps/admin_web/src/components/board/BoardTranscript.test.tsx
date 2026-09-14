import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BoardTurn } from "../../lib/boardModel";
import { BoardTranscript } from "./BoardTranscript";

function turn(overrides: Partial<BoardTurn> = {}): BoardTurn {
  return {
    seq: 1,
    phase: "agenda",
    personaId: "ceo",
    displayName: "Ada",
    title: "CEO",
    text: "Ship the beta.",
    createdAt: "2026-09-14T00:00:00Z",
    usage: { promptTokens: 10, completionTokens: 5, totalTokens: 15, cost: 0.01 },
    model: "openai/gpt-4.1-mini",
    ...overrides,
  };
}

describe("BoardTranscript", () => {
  it("shows the served model on spoken turns", () => {
    render(
      <BoardTranscript
        turns={[turn(), turn({ seq: 2, personaId: "cfo", displayName: "Ben", title: "CFO", model: "anthropic/claude-sonnet-4" })]}
        isRunning={false}
        currentPhaseLabel="Done"
      />,
    );
    expect(screen.getByText(/openai\/gpt-4\.1-mini/)).toBeInTheDocument();
    expect(screen.getByText(/anthropic\/claude-sonnet-4/)).toBeInTheDocument();
  });
});
