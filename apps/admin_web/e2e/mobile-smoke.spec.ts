import { expect, test, type Page } from "@playwright/test";

async function pageHasHorizontalOverflow(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
}

test.describe("admin viewport smoke", () => {
  test("dashboard loads fixture summaries", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("LX Software net")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "About this page" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Hillmarton" })).toBeVisible();
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });

  test("LX Software dashboard shows the OpenRouter bill", async ({ page }) => {
    await page.goto("/lx-software");
    await expect(page.getByRole("heading", { name: "LX Software", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "AWS", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "OpenRouter", exact: true })).toBeVisible();
    const awsMonth = page.getByLabel("AWS month");
    const openrouterMonth = page.getByLabel("OpenRouter month");
    await expect(awsMonth).toBeVisible();
    await expect(openrouterMonth).toBeVisible();
    expect(await awsMonth.locator("option").count()).toBe(13);
    expect(await openrouterMonth.locator("option").count()).toBe(13);
    await expect(page.getByText("LX Software pays the AWS invoice")).toBeVisible();
    await expect(page.getByText("USD 434.12 · 50.6%")).toBeVisible();
    await expect(page.getByText("USD 420.64 · 49.0%")).toBeVisible();
    await expect(page.getByRole("button", { name: "Download allocation PDF" })).toBeVisible();
    await expect(page.getByText("LX Software pays the OpenRouter invoice")).toBeVisible();
    await expect(page.getByText("USD 0.42")).toBeVisible();
    await expect(page.getByText("calls metered in this admin")).toBeVisible();
    await expect(page.getByText("Pulled from OpenRouter", { exact: true })).toHaveCount(2);
    await expect(page.getByText("Pulled from OpenRouter · no spend on this key yet.")).toBeVisible();
    await expect(page.getByText("scratch", { exact: true })).toBeVisible();
    await expect(page.getByText("USD 0.11")).toBeVisible();
    await expect(page.getByText("Other", { exact: true })).toBeVisible();
    await expect(page.getByText("USD 0.18", { exact: true })).toBeVisible();
    await expect(
      page.getByText("OpenRouter Chat and spend that is not on an API key."),
    ).toBeVisible();

    const pastKey = await awsMonth.locator("option").nth(2).getAttribute("value");
    expect(pastKey).toBeTruthy();
    await awsMonth.selectOption(pastKey!);
    await expect(page.getByText(`${pastKey}-01`)).toBeVisible();
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });

  test("finance accounts keep name, balance, and stale warning on phones", async ({
    page,
  }, testInfo) => {
    await page.goto("/finance");
    await expect(page.getByRole("heading", { name: "Finance", level: 1 })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "About this page" })).toHaveCount(0);
    await expect(page.getByText("HSBC HK current")).toBeVisible();
    await expect(page.getByText("128,430.50").first()).toBeVisible();
    await expect(page.getByText("Stale").filter({ visible: true }).first()).toBeVisible();

    if (testInfo.project.name === "phone") {
      await expect(page.locator("#finance-select")).toBeVisible();
      await expect(page.getByLabel("Sort by", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /Sort by /i })).toHaveCount(0);
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

  test("assets lists inbound statement PDFs", async ({ page }) => {
    await page.goto("/assets");
    await expect(page.getByRole("heading", { name: "Assets", level: 1 })).toBeVisible();
    await expect(page.getByText("KDQ170167_-_Landlord_Statement.pdf")).toBeVisible();
    await expect(page.getByText("32 Hillmarton").filter({ visible: true }).first()).toBeVisible();
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });

  test("siu tin dei board sections stay reachable", async ({ page }, testInfo) => {
    await page.goto("/siu-tin-dei");
    await expect(page.getByRole("heading", { name: "Siu Tin Dei", level: 1 })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Executive Board" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("heading", { name: "Daily review" })).toBeVisible();
    await expect(page.getByText(/Three parent threads closed/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Sync from main" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Promote" })).toBeVisible();
    await expect(page.getByText(/board: #42 add booking/i)).toBeVisible();
    if (testInfo.project.name === "phone") {
      await page.locator("#board-section-select").selectOption("progress");
    } else {
      await page.getByRole("tab", { name: /Progress/ }).click();
    }
    await expect(page.getByRole("heading", { name: "Progress" })).toBeVisible();
    await expect(page.getByText("Live listings", { exact: true })).toBeVisible();
    await expect(page.getByText("12 / 1000")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Bulk catalog sources" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Scan sources now" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Preview" }).first()).toBeVisible();
    await page.getByRole("button", { name: "Preview" }).first().click();
    await expect(page.getByRole("cell", { name: "Sha Tin Playhouse" })).toBeVisible();
    await expect(page.getByText(/Listing gap in Tai Po/i)).toBeVisible();
    if (testInfo.project.name === "phone") {
      await expect(page.locator("#board-section-select")).toBeVisible();
      await page.locator("#board-section-select").selectOption("market");
    } else {
      await expect(page.getByRole("tab", { name: /Next actions/ })).toBeVisible();
      await page.getByRole("tab", { name: /Market/ }).click();
    }
    await expect(page.getByRole("heading", { name: "Market" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Kiztopia", exact: true })).toBeVisible();
    if (testInfo.project.name === "phone") {
      await page.locator("#board-section-select").selectOption("pipeline");
    } else {
      await page.getByRole("tab", { name: /Pipeline/ }).click();
    }
    await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Sha Tin Playhouse", exact: true })).toBeVisible();
    if (testInfo.project.name === "phone") {
      await page.locator("#board-section-select").selectOption("content");
    } else {
      await page.getByRole("tab", { name: /Content/ }).click();
    }
    await expect(page.getByRole("heading", { name: "Content" })).toBeVisible();
    await expect(page.getByRole("row", { name: /facebook Saturday play in Sha Tin/i })).toBeVisible();
    if (testInfo.project.name === "phone") {
      await page.locator("#board-section-select").selectOption("staff");
    } else {
      await page.getByRole("tab", { name: /Staff/ }).click();
    }
    await expect(page.getByText("Parent Support").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Run staff tick now" })).toBeVisible();
    await expect(page.getByText(/Up to 6 tasks can run at once/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Open Settings" })).toBeVisible();
    if (testInfo.project.name === "phone") {
      await page.locator("#board-section-select").selectOption("tasks");
    } else {
      await page.getByRole("tab", { name: /Tasks/ }).click();
    }
    await expect(page.getByText("New task")).toBeVisible();
    await expect(page.getByText(/List our three biggest monthly costs/i)).toBeVisible();
    if (testInfo.project.name === "phone") {
      await page.locator("#board-section-select").selectOption("approvals");
    } else {
      await page.getByRole("tab", { name: /Approvals/ }).click();
    }
    await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
    await expect(page.getByLabel("Approval apr-1")).toBeVisible();
    await expect(page.getByText("Send launch confirmation to a newly onboarded provider")).toBeVisible();
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
    if (testInfo.project.name === "phone") {
      await page.locator("#board-section-select").selectOption("settings");
    } else {
      const tablist = page.getByRole("tablist", { name: "Board sections" });
      const lastTab = page.getByRole("tab", { name: /Settings/ });
      await lastTab.scrollIntoViewIfNeeded();
      await expect(lastTab).toBeInViewport();
      const listBox = await tablist.boundingBox();
      const tabBox = await lastTab.boundingBox();
      expect(listBox).toBeTruthy();
      expect(tabBox).toBeTruthy();
      expect(tabBox!.x + tabBox!.width).toBeLessThanOrEqual(listBox!.x + listBox!.width + 2);
      await lastTab.click();
    }
    await expect(page.getByLabel("Concurrent tasks")).toBeVisible();
    await expect(page.getByLabel("Concurrent tasks")).toHaveValue("6");
    await expect(page.getByLabel("Staff daily budget in USD")).toBeVisible();
    await expect(
      page.getByLabel("Run 3-per-district catalog micro-batch (pause while bulk import fills the catalog)"),
    ).toBeVisible();
  });

  test("deep-linked account hydrates, and a dirty switch asks first", async ({ page }) => {
    await page.goto("/finance?account=ac-1&liability=li-1");
    const description = page.getByRole("textbox", { name: "Description" });
    await expect(description).toHaveValue("HSBC HK current");
    await expect(page.getByRole("button", { name: "Update record" })).toBeVisible();
    await expect(page).toHaveURL(/account=ac-1/);
    await expect(page).not.toHaveURL(/liability=/);
    await description.fill("HSBC edited");
    await page.getByRole("row", { name: /Monzo/ }).click();
    await expect(page.getByRole("heading", { name: "Discard unsaved edits?" })).toBeVisible();
    await page.getByRole("button", { name: "Keep editing" }).click();
    await expect(description).toHaveValue("HSBC edited");
    await page.getByRole("button", { name: "Update record" }).click();
    await expect(page.getByRole("cell", { name: /HSBC edited/ }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Update record" })).toHaveCount(0);
  });

  test("an unknown account id is removed instead of opening a blank editor", async ({ page }) => {
    await page.goto("/finance?account=does-not-exist");
    await expect(page.getByRole("button", { name: "Update record" })).toHaveCount(0);
    await expect(page).not.toHaveURL(/account=/);
    await expect(page.getByText("HSBC HK current")).toBeVisible();
  });

  test("a new statement line uses an Add line button", async ({ page }, testInfo) => {
    await page.goto("/finance");
    if (testInfo.project.name === "phone") {
      await page.locator("#finance-select").selectOption("hillmarton");
    } else {
      await page.locator("#finance-tab-hillmarton").click();
    }
    await page.getByRole("button", { name: "New line" }).click();
    const addLine = page.getByRole("button", { name: "Add line" });
    await expect(addLine).toBeVisible();
    await expect(addLine).toHaveText("Add line");
    expect(await pageHasHorizontalOverflow(page)).toBe(false);
  });
});
