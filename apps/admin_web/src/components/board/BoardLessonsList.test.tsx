import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardLesson } from "../../lib/boardModel";
import { BoardLessonsList } from "./BoardLessonsList";

const PENDING_ID = "44d4ca06c8f24d5aa5f1d8b9c1e7a2f0";
const CONFIRMED_ID = "9a1b2c3d4e5f60718293a4b5c6d7e8f9";

function lesson(overrides: Partial<BoardLesson> = {}): BoardLesson {
  return {
    lessonId: PENDING_ID,
    kind: "veto",
    subject: "content-marketer",
    classKey: "publish:facebook",
    what: "Scheduled a post outside the launch district.",
    instruction: "Only post about Stanley listings.",
    confirmed: false,
    dismissed: false,
    createdAt: "2026-11-08T00:00:00Z",
    ...overrides,
  };
}

describe("BoardLessonsList ids", () => {
  it("shows the full lesson id on a pending lesson so the owner can match it to a report", () => {
    render(<BoardLessonsList lessons={[lesson()]} onConfirm={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByLabelText(`Lesson ${PENDING_ID}`)).toHaveTextContent(PENDING_ID);
    expect(screen.getByLabelText(`Copy lesson id ${PENDING_ID}`)).toBeInTheDocument();
  });

  it("shows the short id on confirmed lessons", () => {
    render(
      <BoardLessonsList
        lessons={[lesson({ lessonId: CONFIRMED_ID, confirmed: true, instruction: "Stanley only." })]}
        onConfirm={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(`Lesson ${CONFIRMED_ID}`)).toHaveTextContent(`#${CONFIRMED_ID.slice(0, 8)}`);
    expect(screen.getByText("Stanley only.")).toBeInTheDocument();
  });

  it("confirms and dismisses with the lesson id", () => {
    const onConfirm = vi.fn();
    const onDismiss = vi.fn();
    render(<BoardLessonsList lessons={[lesson()]} onConfirm={onConfirm} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith(PENDING_ID, undefined);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledWith(PENDING_ID);
  });
});
