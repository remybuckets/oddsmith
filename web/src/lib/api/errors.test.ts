import { describe, expect, test } from "vitest";
import { ApiRequestError, CONNECTION_MESSAGE, fromErrorResponse, fromNetworkFailure } from "./errors";

describe("fromErrorResponse", () => {
  test("keeps the code, message, status and retry time from an error envelope", () => {
    const body = {
      success: false,
      data: null,
      error: {
        code: "daily_limit_reached",
        message: "You've used today's questions.",
        retry_at: "2026-10-08T23:00:00Z",
      },
    };

    const err = fromErrorResponse(429, body);

    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err.code).toBe("daily_limit_reached");
    expect(err.message).toBe("You've used today's questions.");
    expect(err.status).toBe(429);
    expect(err.retryAt).toBe("2026-10-08T23:00:00Z");
  });

  test("treats a missing retry time as null", () => {
    const body = { success: false, data: null, error: { code: "not_found", message: "Gone." } };

    expect(fromErrorResponse(404, body).retryAt).toBeNull();
  });

  test.each([
    ["a non-envelope body", { detail: "Bad gateway" }],
    ["an empty body", undefined],
    ["an unknown error code", { success: false, data: null, error: { code: "teapot", message: "x" } }],
    ["a missing message", { success: false, data: null, error: { code: "internal" } }],
  ])("falls back to an internal error for %s", (_label, body) => {
    const err = fromErrorResponse(502, body);

    expect(err.code).toBe("internal");
    expect(err.status).toBe(502);
    expect(err.message).toMatch(/something went wrong/i);
  });
});

describe("fromNetworkFailure", () => {
  test("reports a connection problem with status 0", () => {
    const err = fromNetworkFailure(new TypeError("Failed to fetch"));

    expect(err.code).toBe("internal");
    expect(err.status).toBe(0);
    expect(err.message).toBe(CONNECTION_MESSAGE);
    expect(err.cause).toBeInstanceOf(TypeError);
  });
});
