import { describe, expect, it } from "vitest";
import { BOARD_CONTENT_KEY } from "./useBoardContent";
import { BOARD_QUERY_KEY } from "./useBoard";

describe("useBoardContent keys", () => {
  it("nests under the board query key", () => {
    expect(BOARD_CONTENT_KEY[0]).toBe(BOARD_QUERY_KEY[0]);
    expect(BOARD_CONTENT_KEY).toContain("content");
  });
});
