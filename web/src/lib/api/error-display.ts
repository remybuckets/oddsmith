import { formatUkDateTime, formatUkTime } from "@/lib/format/time";
import type { ApiRequestError } from "./errors";
import type { ApiErrorCode } from "./types";

export type ErrorPresentation = "banner" | "screen" | "redirect";

export interface ErrorDisplay {
  title: string;
  /** The server's message, shown as-is. */
  body: string;
  presentation: ErrorPresentation;
  redirectTo: string | null;
  /** When the block lifts, in UK time, if the server said. */
  retryLabel: string | null;
  /** Show GamCare and GAMSTOP alongside the message. */
  showSupport: boolean;
}

interface DisplayRule {
  title: string;
  presentation: ErrorPresentation;
  redirectTo?: string;
  showSupport?: boolean;
  retryLabel?: (retryAt: string) => string;
}

const RULES: Record<ApiErrorCode, DisplayRule> = {
  unauthenticated: { title: "Please sign in", presentation: "redirect", redirectTo: "/sign-in" },
  age_not_confirmed: {
    title: "One quick check first",
    presentation: "redirect",
    redirectTo: "/onboarding",
  },
  on_break: {
    title: "You're on a break",
    presentation: "screen",
    showSupport: true,
    retryLabel: (at) => `Your break ends ${formatUkDateTime(at)}`,
  },
  daily_limit_reached: {
    title: "Back tomorrow",
    presentation: "banner",
    retryLabel: (at) => `Questions reset ${formatUkDateTime(at)}`,
  },
  rate_limited: {
    title: "Slow down a moment",
    presentation: "banner",
    retryLabel: (at) => `Try again after ${formatUkTime(at)}`,
  },
  budget_exhausted: {
    title: "Back tomorrow",
    presentation: "banner",
    retryLabel: (at) => `Back ${formatUkDateTime(at)}`,
  },
  not_found: { title: "Not found", presentation: "banner" },
  invalid_input: { title: "That didn't work", presentation: "banner" },
  internal: { title: "Something went wrong", presentation: "banner" },
};

export function describeApiError(error: ApiRequestError): ErrorDisplay {
  const rule = RULES[error.code];
  return {
    title: rule.title,
    body: error.message,
    presentation: rule.presentation,
    redirectTo: rule.redirectTo ?? null,
    retryLabel: rule.retryLabel && error.retryAt ? rule.retryLabel(error.retryAt) : null,
    showSupport: rule.showSupport ?? false,
  };
}
