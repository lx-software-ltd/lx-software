import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetchJson } from "../lib/apiAdminClient";
import { reviewWrongMutationOptions, rampPromoteMutationOptions, stagingPromoteMutationOptions } from "./useBoardReview";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const fetchMock = vi.mocked(adminFetchJson);

describe("review mutations", () => {
  let qc: QueryClient;

  beforeEach(() => {
    fetchMock.mockReset();
    qc = new QueryClient();
  });

  it("posts a correction to the sample wrong path", async () => {
    fetchMock.mockResolvedValueOnce({ lesson: { lessonId: "lsn-1", instruction: "x" } });
    const { mutationFn } = reviewWrongMutationOptions(qc);
    await mutationFn({ callId: "call-1", note: "too casual" });
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/siu-tin-dei/board/review/sample/call-1/wrong");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ note: "too casual" });
  });

  it("posts promote to the encoded class key", async () => {
    fetchMock.mockResolvedValueOnce({ classKey: "publish:facebook" });
    const { mutationFn } = rampPromoteMutationOptions(qc);
    await mutationFn("publish:facebook");
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/siu-tin-dei/board/ramp/publish%3Afacebook/promote");
    expect(init?.method).toBe("POST");
  });

  it("posts staging promote", async () => {
    fetchMock.mockResolvedValueOnce({ approval: { approvalId: "appr-1" }, preview: { aheadBy: 1 } });
    const { mutationFn } = stagingPromoteMutationOptions(qc);
    await mutationFn();
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/siu-tin-dei/board/code/promote");
    expect(init?.method).toBe("POST");
  });
});
