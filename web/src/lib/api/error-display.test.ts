import { describe, expect, test } from "vitest";
import { describeApiError } from "./error-display";
import { ApiRequestError } from "./errors";
import { API_ERROR_CODES, type ApiErrorCode } from "./types";

const BANNED_WORDS = /\b(lock|banker|guaranteed|sure thing)\b/i;

function errorFor(code: ApiErrorCode, retryAt: string | null = null) {
  return new ApiRequestError({ code, message: "Server message.", status: 400, retryAt });
}

describe("describeApiError", () => {
  test.each(API_ERROR_CODES)("gives %s a title, the server message and no banned words", (code) => {
    const display = describeApiError(errorFor(code));

    expect(display.title.length).toBeGreaterThan(0);
    expect(display.body).toBe("Server message.");
    expect(`${display.title} ${display.body}`).not.toMatch(BANNED_WORDS);
  });

  test.each([
    ["daily_limit_reached", "Back tomorrow"],
    ["budget_exhausted", "Back tomorrow"],
  ] as const)("titles %s as %s", (code, title) => {
    expect(describeApiError(errorFor(code)).title).toBe(title);
  });

  test("sends unauthenticated users to sign in", () => {
    expect(describeApiError(errorFor("unauthenticated"))).toMatchObject({
      presentation: "redirect",
      redirectTo: "/sign-in",
    });
  });

  test("sends users without an 18+ declaration to onboarding", () => {
    expect(describeApiError(errorFor("age_not_confirmed"))).toMatchObject({
      presentation: "redirect",
      redirectTo: "/onboarding",
    });
  });

  test("shows a break as a full screen with support details", () => {
    const display = describeApiError(errorFor("on_break", "2026-10-15T14:00:00Z"));

    expect(display.presentation).toBe("screen");
    expect(display.showSupport).toBe(true);
    expect(display.retryLabel).toBe("Your break ends Thu 15 Oct, 15:00");
  });

  test("shows limits as a banner with the UK time they lift", () => {
    const display = describeApiError(errorFor("daily_limit_reached", "2026-10-08T23:00:00Z"));

    expect(display.presentation).toBe("banner");
    expect(display.retryLabel).toBe("Questions reset Fri 9 Oct, 00:00");
  });

  test("gives a short retry label for the per-minute rate limit", () => {
    const display = describeApiError(errorFor("rate_limited", "2026-10-08T14:01:00Z"));

    expect(display.retryLabel).toBe("Try again after 15:01");
  });

  test("leaves the retry label empty when the server sends no retry time", () => {
    expect(describeApiError(errorFor("daily_limit_reached")).retryLabel).toBeNull();
  });

  test.each(["rate_limited", "not_found", "invalid_input", "internal"] as const)(
    "shows %s as a banner without support details",
    (code) => {
      expect(describeApiError(errorFor(code))).toMatchObject({ presentation: "banner", showSupport: false });
    },
  );
});
