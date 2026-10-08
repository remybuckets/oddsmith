import { expect, type APIRequestContext, test } from "@playwright/test";

// Runs against the real local stack: `supabase start` (with its Mailpit inbox), Redis, and the
// API on :8000 (fake orchestrator until that lane merges). Local Supabase sends at most 2 auth
// emails an hour, so this runs on one project only.
const INBOX = process.env.E2E_INBOX_URL ?? "http://127.0.0.1:54324";
const MAGIC_LINK = /http:\/\/(?:127\.0\.0\.1|localhost):54321\/auth\/v1\/verify\?[^\s"'<>)\]]+/;
const INBOX_TIMEOUT_MS = 20_000;
// The whole journey: email delivery plus five screens (first visits compile under `next dev`).
const FLOW_TIMEOUT_MS = 120_000;

interface InboxSearch {
  messages: { ID: string }[];
}

async function magicLinkFor(request: APIRequestContext, email: string): Promise<string> {
  let link: string | undefined;
  await expect
    .poll(
      async () => {
        const search = await request.get(`${INBOX}/api/v1/search`, { params: { query: `to:"${email}"` } });
        const { messages } = (await search.json()) as InboxSearch;
        if (messages.length === 0) return false;
        const message = await request.get(`${INBOX}/api/v1/message/${messages[0].ID}`);
        const { Text, HTML } = (await message.json()) as { Text: string; HTML: string };
        link = `${Text}\n${HTML}`.match(MAGIC_LINK)?.[0].replaceAll("&amp;", "&");
        return Boolean(link);
      },
      { timeout: INBOX_TIMEOUT_MS, message: `magic link email for ${email}` },
    )
    .toBe(true);
  return link!;
}

test("sign in, confirm 18+, ask a question and see the answer's card", async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "one magic-link email per run (local rate limit)");
  test.setTimeout(FLOW_TIMEOUT_MS);
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/");
  await page.getByRole("link", { name: "Sign in" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Email me a sign-in link" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();

  await page.goto(await magicLinkFor(request, email));

  await expect(page).toHaveURL(/\/onboarding$/);
  const continueButton = page.getByRole("button", { name: "Continue" });
  await expect(continueButton).toBeDisabled();
  await page.getByRole("checkbox", { name: /I'm 18 or over/ }).click();
  await continueButton.click();
  await expect(page.getByRole("heading", { name: "How Oddsmith works" })).toBeVisible();
  await page.getByRole("button", { name: "Start asking" }).click();

  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.getByText(/^Matchweek \d+$/)).toBeVisible();
  await page.getByRole("textbox", { name: "Ask Oddsmith" }).fill("How has Saka done away from home?");
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("How has Saka done away from home?")).toBeVisible();
  await expect(page.getByText(/placeholder answer/i)).toBeVisible();
  await expect(page.getByText("Placeholder", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Sources: API-Football/)).toBeVisible();
  await expect(page.getByText("14 questions left today")).toBeVisible();

  await page.getByRole("button", { name: "Helpful" }).click();
  await expect(page.getByRole("button", { name: "Helpful" })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByText("1 of 15 questions used today")).toBeVisible();
});
