import { expect, type Page, test } from "@playwright/test";

const PASSWORD = "a long test passphrase";

async function signUp(page: Page) {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.in`;
  await page.goto("/");
  await page.getByRole("link", { name: "Create an account" }).first().click();
  await page.getByLabel("Your name").fill("Test Trader");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/app$/);
  return email;
}

test("pages behind login send you to log in", async ({ page }) => {
  await page.goto("/app/history");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("help@example.in")).toBeVisible();
});

test("a full Write: question, answer, checked code, history", async ({ page }) => {
  await signUp(page);
  await expect(page.getByText("20 of 20 answers left today")).toBeVisible();

  await page.getByLabel("Market").selectOption("nse_eq");
  await page.getByLabel("Timeframe").selectOption("daily");
  await page.getByLabel("Describe your strategy").fill("A moving average crossover?");
  await page.getByRole("button", { name: "Write the code" }).click();

  // The direction was missing, so it asks first, and that costs nothing.
  await expect(page.getByText("Should it trade long only, short only, or both?")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page).toHaveURL(/\/app\/c\/[0-9a-f-]{36}$/);
  await expect(page.getByText("20 of 20 answers left today")).toBeVisible();

  await page
    .getByLabel("Your answer")
    .fill(
      "Long only. Buy on the fast average crossing above the slow one, sell on the cross back.",
    );
  await page.getByRole("button", { name: "Send answer" }).click();

  // Progress shows step by step, then the checked answer.
  await expect(page.getByText("Writing the code")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Checked", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("figure", { name: "Code" })).toContainText(
    "Buy = Cross(Fast, Slow);",
  );
  await expect(page.getByRole("region", { name: "Checks" })).toContainText(
    "No signal reads a future bar",
  );
  await expect(page.getByText("Offline demo: this answer was written by a script")).toBeVisible();
  await expect(page.getByRole("link", { name: "SetTradeDelays" })).toHaveAttribute(
    "href",
    "https://www.amibroker.com/guide/afl/settradedelays.html",
  );
  await expect(page.getByText("19 of 20 answers left today")).toBeVisible();

  await page.getByRole("button", { name: "Yes" }).click();
  await expect(page.getByText("Thank you.")).toBeVisible();

  // History keeps it, and reopening shows the same answer.
  await page.getByRole("link", { name: "History" }).click();
  await page.getByRole("link", { name: /A moving average crossover/ }).click();
  await expect(page.getByText("Checked", { exact: true })).toBeVisible();
  await expect(page.getByRole("figure", { name: "Code" })).toContainText(
    "Sell = Cross(Slow, Fast);",
  );
});

test("a full Review: verified and AI findings apart, then apply all fixes", async ({ page }) => {
  await signUp(page);
  await page.getByText("Review", { exact: true }).click();
  await page.getByLabel("Market").selectOption("nse_eq");
  await page.getByLabel("Timeframe").selectOption("daily");
  await page
    .getByLabel("Your AFL code")
    .fill(
      "SetTradeDelays(1, 1, 1, 1);\nFast = EMA(Close, 9);\nSlow = EMA(Close, 21);\nBuy = Cross(Fast, Slow) AND Ref(Close, 1) > Close;\nSell = Cross(Slow, Fast);\n",
    );
  await page.getByRole("button", { name: "Review the code" }).click();

  const verified = page.getByRole("region", { name: "Verified by the checker" }).first();
  const ai = page.getByRole("region", { name: "Suggested by the AI review" });
  await expect(verified).toContainText("reads future bars", { timeout: 30_000 });
  await expect(verified).toContainText("Line 4");
  await expect(ai).toContainText("Nothing here is verified");
  await expect(ai).toContainText("Cross");

  await page.getByRole("button", { name: "Apply all fixes" }).click();
  await expect(page.getByText("Checked", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByText(/Some of these fixes were AI-suggested|written by a script/).first(),
  ).toBeVisible();
});

test("log out ends the session", async ({ page }) => {
  await signUp(page);
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login$/);
});
