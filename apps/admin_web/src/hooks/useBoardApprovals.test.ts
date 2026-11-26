import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BoardApproval } from "../lib/boardModel";
import { adminFetchJson } from "../lib/apiAdminClient";
import { BOARD_QUERY_KEY } from "./useBoard";
import { approvalDecisionMutationOptions, BOARD_APPROVALS_KEY } from "./useBoardApprovals";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const fetchMock = vi.mocked(adminFetchJson);

function approval(overrides: Partial<BoardApproval> = {}): BoardApproval {
  return {
    approvalId: "apr-1",
    status: "pending",
    personaId: "cto",
    displayName: "Ada",
    toolId: "mail",
    toolLabel: "Email",
    op: "send",
    kind: "write",
    arguments: { to: "coach@example.com", subject: "Hello" },
    summary: "Send a note to the coach",
    reason: "Recipient is not on the allow-list",
    context: { kind: "chat" },
    ...overrides,
  } as BoardApproval;
}

describe("approvalDecisionMutationOptions", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    qc = new QueryClient();
  });

  it("posts the note and the edited arguments on approve", async () => {
    fetchMock.mockResolvedValueOnce({ approval: approval({ status: "executed" }) });
    const { mutationFn } = approvalDecisionMutationOptions(qc);
    const edited = { to: "coach@example.com", subject: "Edited" };

    await mutationFn({ approvalId: "apr-1", decision: "approve", note: "ok", arguments: edited });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/v1/admin/siutindei/board/approvals/apr-1/approve");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ note: "ok", arguments: edited });
  });

  it("never sends arguments on reject, even when the caller passes them", async () => {
    fetchMock.mockResolvedValueOnce({ approval: approval({ status: "rejected" }) });
    const { mutationFn } = approvalDecisionMutationOptions(qc);

    await mutationFn({ approvalId: "apr-1", decision: "reject", arguments: { subject: "Edited" } });

    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/v1/admin/siutindei/board/approvals/apr-1/reject");
    expect(JSON.parse(init?.body as string)).toEqual({ note: "" });
  });

  it("defaults the note to an empty string", async () => {
    fetchMock.mockResolvedValueOnce({ approval: approval() });
    const { mutationFn } = approvalDecisionMutationOptions(qc);

    await mutationFn({ approvalId: "apr-1", decision: "approve" });

    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ note: "" });
  });

  it("invalidates the board root on approve so mail, receivables and meta refetch", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = approvalDecisionMutationOptions(qc);

    onSuccess(approval({ status: "executed" }), { approvalId: "apr-1", decision: "approve" });

    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY });
    expect(spy.mock.calls[0][0]).not.toHaveProperty("exact");
  });

  it("invalidates the board root when the approval reports executed", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = approvalDecisionMutationOptions(qc);

    onSuccess(approval({ status: "executed" }), { approvalId: "apr-1", decision: "reject" });

    expect(spy).toHaveBeenCalledWith({ queryKey: BOARD_QUERY_KEY });
  });

  it("keeps the narrow invalidation on reject", () => {
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { onSuccess } = approvalDecisionMutationOptions(qc);

    onSuccess(approval({ status: "rejected" }), { approvalId: "apr-1", decision: "reject" });

    const keys = spy.mock.calls.map(([filters]) => filters);
    expect(keys).toContainEqual({ queryKey: BOARD_APPROVALS_KEY });
    expect(keys).toContainEqual({ queryKey: BOARD_QUERY_KEY, exact: true });
    expect(keys).toContainEqual({ queryKey: [...BOARD_QUERY_KEY, "toolCalls"] });
    expect(keys).toContainEqual({ queryKey: [...BOARD_QUERY_KEY, "actions"] });
    expect(keys).not.toContainEqual({ queryKey: BOARD_QUERY_KEY });
  });

  it("replaces the decided approval in the cached list", () => {
    qc.setQueryData<BoardApproval[]>(BOARD_APPROVALS_KEY, [approval(), approval({ approvalId: "apr-2" })]);
    const { onSuccess } = approvalDecisionMutationOptions(qc);

    onSuccess(approval({ status: "rejected", note: "no" } as Partial<BoardApproval>), {
      approvalId: "apr-1",
      decision: "reject",
    });

    const cached = qc.getQueryData<BoardApproval[]>(BOARD_APPROVALS_KEY) ?? [];
    expect(cached.map((a) => [a.approvalId, a.status])).toEqual([
      ["apr-1", "rejected"],
      ["apr-2", "pending"],
    ]);
  });
});
