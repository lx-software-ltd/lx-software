import { expect, test, type Page } from "@playwright/test";

async function pageHasHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
}

test.describe("admin viewport smoke", () => {
  test("dashboard loads fixture summaries", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "OpenRouter this month" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Hillmarton" })).toBeVisible();
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });

  test("finance accounts keep name, balance, and stale warning on phones", async ({
    page,
  }, testInfo) => {
    await page.goto("/finance");
    await expect(page.getByRole("heading", { name: "Finance", level: 1 })).toBeVisible();
    await expect(page.getByText("HSBC HK current")).toBeVisible();
    await expect(page.getByText("128,430.50").first()).toBeVisible();
    await expect(page.getByText("Stale").filter({ visible: true }).first()).toBeVisible();

    if (testInfo.project.name === "phone") {
      await expect(page.locator("#finance-select")).toBeVisible();
      await expect(page.getByLabel("Sort by", { exact: true })).toBeVisible();
      await expect(page.getByRole("columnheader", { name: /Account Type/i })).toBeHidden();
    } else {
      await expect(page.getByRole("tab", { name: "Accounts" })).toBeVisible();
    }
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });

  test("investments keep current value on phones", async ({ page }, testInfo) => {
    await page.goto("/finance");
    if (testInfo.project.name === "phone") {
      await page.locator("#finance-select").selectOption("investments");
    } else {
      await page.locator("#finance-tab-investments").click();
    }
    await expect(page.getByRole("cell", { name: /Hillmarton Road/ }).first()).toBeVisible();
    await expect(page.getByText("512,000.00").or(page.getByText("512,000")).first()).toBeVisible();
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });

  test("banking shows expiring consent on phones", async ({ page }, testInfo) => {
    await page.goto("/banking");
    await expect(page.getByRole("heading", { name: "Banking", level: 1 })).toBeVisible();
    await expect(page.getByRole("cell", { name: /Monzo/ }).first()).toBeVisible();
    await expect(page.getByText(/Consent expires/i).filter({ visible: true }).first()).toBeVisible();
    if (testInfo.project.name === "desktop") {
      await expect(page.getByRole("columnheader", { name: /Consent valid until/i })).toBeVisible();
    }
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });

  test("siu tin dei board sections stay reachable", async ({ page }, testInfo) => {
    await page.goto("/siu-tin-dei");
    await expect(page.getByRole("heading", { name: "Siu Tin Dei", level: 1 })).toBeVisible();
    await page.getByRole("tab", { name: "Executive Board" }).click();
    await expect(page.getByText(/Ship the provider onboarding form/i)).toBeVisible();
    if (testInfo.project.name === "phone") {
      await expect(page.locator("#board-section-select")).toBeVisible();
    } else {
      await expect(page.getByRole("tab", { name: /Next actions/ })).toBeVisible();
    }
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });
});
