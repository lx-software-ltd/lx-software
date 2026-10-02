import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { adminFetchJson } from "../lib/apiAdminClient";
import type { HouseFinanceData } from "../lib/financeModel";
import { keys } from "../lib/queryKeys";
import { saveHouseMutationOptions } from "./useFinance";

vi.mock("../lib/apiAdminClient", () => ({
  adminFetchJson: vi.fn(),
}));

const house: HouseFinanceData = {
  defaultCurrency: "HKD",
  float: { amount: 0, currency: "HKD" },
  lines: [],
};

describe("saveHouseMutationOptions", () => {
  let qc: QueryClient;

  beforeEach(() => {
    vi.mocked(adminFetchJson).mockReset();
    qc = new QueryClient();
  });

  it("writes the saved house onto the finance query", () => {
    const { onSuccess } = saveHouseMutationOptions(qc);
    onSuccess({ house: "hillmarton", data: house }, { house: "hillmarton", data: house }, undefined);
    expect(qc.getQueryData(keys.finance)).toMatchObject({ hillmarton: house });
  });
});
