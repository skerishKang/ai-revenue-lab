import { expect, test, type Page } from "@playwright/test";

/**
 * #5298 — first-screen browser verification.
 *
 * Scope: the clone renders, the shell is operable, the theme switches, the
 * composer sends, and the browser console stays clean. Live API behaviour is
 * explicitly out of scope — the clone answers from local fixtures.
 */

async function collectConsoleErrors(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => {
    errors.push(`pageerror: ${error.message}`);
  });
  return errors;
}

/**
 * The first screen must render without waiting for the external font files, so
 * the navigation waits for the document and not for every font request.
 */
async function open(page: Page) {
  await page.goto("/", { waitUntil: "domcontentloaded", timeout: 60000 });
}

test("first screen renders with the operational shell", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await open(page);

  await expect(page.locator(".app-shell")).toHaveAttribute("data-state", "home");
  await expect(page.locator("#sidebar")).toBeVisible();
  await expect(page.locator("#emptyState")).toBeVisible();
  await expect(page.locator("#composerForm")).toBeVisible();
  await expect(page.locator("#messageInput")).toBeVisible();
  await expect(page.getByText("무엇을 도와드릴까요?")).toBeVisible();

  expect(errors).toEqual([]);
});

test("the sidebar shows the recent conversations and switches between them", async ({
  page,
  isMobile,
}) => {
  await open(page);
  if (isMobile) {
    // On the mobile layout the sidebar is a drawer; it has to be opened before
    // a recent conversation can be reached.
    await page.locator("#mobileMenu").click();
    await expect(page.locator("#sidebar")).toBeInViewport();
  }
  const history = page.locator("#historyList .history-item");
  await expect(history.first()).toBeVisible();
  await history.nth(1).click();
  await expect(history.nth(1)).toHaveAttribute("aria-current", "true");
});

test("the composer sends a turn and the fixture answer arrives", async ({ page }) => {
  const errors = await collectConsoleErrors(page);
  await open(page);

  await page.locator("#messageInput").fill("견적서 초안을 준비해줘");
  await page.locator("#sendButton").click();

  await expect(page.locator("#messageList")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".user-message .message-bubble")).toHaveText(
    "견적서 초안을 준비해줘",
  );
  await expect(page.locator(".assistant-message")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#emptyState")).toBeHidden();
  // The operational product publishes "chat" once a turn exists.
  await expect(page.locator(".app-shell")).toHaveAttribute("data-state", "chat");
  // A fixture answer must never read as a live product answer.
  await expect(page.locator(".assistant-message .demo-label")).toHaveText("fixture 응답");

  expect(errors).toEqual([]);
});

test("the theme switch changes the rendered theme", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "테마" }).click();
  await page.getByRole("button", { name: "Dark", exact: true }).click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page).toHaveURL(/theme=dark/);
});

test("the first screen does not overflow horizontally", async ({ page }) => {
  await open(page);
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.innerWidth + 1);

  await page.getByRole("button", { name: "테마" }).click();
  const openOverflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(openOverflow.scrollWidth).toBeLessThanOrEqual(openOverflow.innerWidth + 1);
});

test("the mobile layout opens the sidebar from the menu button", async ({ page, isMobile }) => {
  test.skip(!isMobile, "mobile-only behaviour");
  await open(page);

  await expect(page.locator("#sidebar")).not.toBeInViewport();
  await page.locator("#mobileMenu").click();
  await expect(page.locator("#sidebar")).toBeInViewport();
});
