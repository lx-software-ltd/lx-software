import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BoardApproval, BoardMember } from "../../lib/boardModel";
import { BoardApprovalsList } from "./BoardApprovalsList";

function approval(overrides: Partial<BoardApproval> = {}): BoardApproval {
  return {
    approvalId: "apr-1",
    status: "pending",
    personaId: "cmo",
    displayName: "CMO",
    toolId: "mail",
    toolLabel: "Mail",
    op: "mail_send",
    kind: "write",
    arguments: { to: ["contact#3"], subject: "Listing is live", body: "Hello" },
    summary: "Send launch confirmation to a newly onboarded provider",
    reason: "Recipient is outside the allow-list",
    context: { kind: "meeting", meetingId: "mtg-3", phase: "round" },
    createdAt: "2026-09-14T00:00:00Z",
    updatedAt: "2026-09-14T00:00:00Z",
    ...overrides,
  };
}

const members: BoardMember[] = [
  {
    id: "cmo",
    title: "Chief Marketing Officer",
    shortName: "Ada",
    focusAreas: [],
    kpisOwned: [],
    vision: "",
    mission: "",
    mandate: "",
    displayName: "Ada",
    defaults: { vision: "", mission: "", mandate: "" },
    isOverridden: { vision: false, mission: false, mandate: false, displayName: true },
    profileHash: "test",
  },
];

describe("BoardApprovalsList", () => {
  it("shows the approval id with the other row fields", () => {
    render(
      <BoardApprovalsList
        approvals={[approval()]}
        members={members}
        isLoading={false}
        isDeciding={false}
        onDecide={vi.fn()}
        onOpenMeeting={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Approval apr-1")).toHaveTextContent("apr-1");
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("Mail")).toBeInTheDocument();
    expect(screen.getByText("Send launch confirmation to a newly onboarded provider")).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("mail_send")).toBeInTheDocument();
    expect(screen.getByText("Recipient is outside the allow-list")).toBeInTheDocument();
  });

  it("shows the full approval id rather than a shortened prefix", () => {
    const approvalId = "a1b2c3d4e5f6789012345678abcdef01";
    render(
      <BoardApprovalsList
        approvals={[approval({ approvalId })]}
        members={members}
        isLoading={false}
        isDeciding={false}
        onDecide={vi.fn()}
        onOpenMeeting={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(`Approval ${approvalId}`)).toHaveTextContent(approvalId);
  });
});
