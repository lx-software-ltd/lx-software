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

  function renderList(item: BoardApproval) {
    render(
      <BoardApprovalsList approvals={[item]} members={members} isLoading={false} isDeciding={false} onDecide={vi.fn()} onOpenMeeting={vi.fn()} />,
    );
  }

  function metaPreview(overrides: Record<string, unknown>): BoardApproval["preview"] {
    const preview = { kind: "meta", from: "facebook", to: [], cc: [], subject: "", text: "", threadId: "", sendEnabled: true, ...overrides };
    return preview as unknown as BoardApproval["preview"];
  }

  it("keeps the budget and targets visible on an ad set approval", () => {
    renderList(
      approval({
        toolId: "meta",
        toolLabel: "Meta",
        op: "meta_create_ad_set",
        arguments: { campaignId: "1200000000001", name: "Stanley parents", dailyBudgetUsd: 15, countries: ["HK"] },
        preview: metaPreview({ subject: "Stanley parents" }),
      }),
    );

    expect(screen.getByText("dailyBudgetUsd")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("1200000000001")).toBeInTheDocument();
    expect(screen.queryByText("from")).not.toBeInTheDocument();
  });

  it("keeps the argument table for a preview from another tool", () => {
    renderList(
      approval({
        toolId: "stores",
        op: "stores_reply_review",
        arguments: { store: "apple", reviewId: "rev-7", message: "Thank you" },
        preview: metaPreview({ kind: "stores", from: "apple", to: ["rev-7"], text: "Thank you" }),
      }),
    );

    expect(screen.getByText("reviewId")).toBeInTheDocument();
  });

  it("shows a WhatsApp reply as a message, with a link that opens the phone app in a new tab", () => {
    renderList(
      approval({
        toolId: "meta",
        op: "meta_reply_whatsapp",
        arguments: { threadId: "thread-1", message: "Thanks, see you Saturday" },
        preview: metaPreview({
          from: "whatsapp",
          to: ["+85255500100"],
          text: "Thanks, see you Saturday",
          threadId: "thread-1",
          phoneLink: "https://wa.me/85255500100?text=Thanks",
        }),
      }),
    );

    expect(screen.getByText("+85255500100")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open in WhatsApp" });
    expect(link).toHaveAttribute("href", "https://wa.me/85255500100?text=Thanks");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/goes out twice/)).toBeInTheDocument();
    expect(screen.queryByText("threadId")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open thread/ })).not.toBeInTheDocument();
  });
});
