import { describe, expect, it } from "vitest";
import { bankAccountLabel, consentDaysRemaining } from "./bankSyncModel";

describe("bankAccountLabel", () => {
  it("joins name and identifier", () => {
    expect(
      bankAccountLabel({
        uid: "u1",
        name: "Current Account",
        identifier: "GB33BUKB20201555555555",
      }),
    ).toBe("Current Account · GB33BUKB20201555555555");
  });

  it("falls back to product when name is missing", () => {
    expect(bankAccountLabel({ uid: "u1", product: "Savings" })).toBe("Savings");
  });

  it("falls back to uid when nothing else is present", () => {
    expect(bankAccountLabel({ uid: "u1" })).toBe("u1");
  });
});

describe("consentDaysRemaining", () => {
  const now = new Date("2026-09-05T00:00:00.000Z");

  it("returns whole days until expiry", () => {
    expect(consentDaysRemaining("2026-09-14T12:00:00.000Z", now)).toBe(9);
  });

  it("is negative once expired", () => {
    expect(consentDaysRemaining("2026-09-01T00:00:00.000Z", now)).toBe(-4);
  });

  it("returns null when the instant is missing or unparseable", () => {
    expect(consentDaysRemaining(undefined, now)).toBeNull();
    expect(consentDaysRemaining("not-a-date", now)).toBeNull();
  });
});
