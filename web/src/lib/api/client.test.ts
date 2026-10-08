import { http, HttpResponse } from "msw";
import { describe, expect, test } from "vitest";
import { sseResponse } from "@/lib/chat/test-helpers";
import { server } from "@/mocks/server";
import { createApiClient } from "./client";
import { ApiRequestError } from "./errors";
import type { Me } from "./types";

const BASE = "http://api.test";
const TOKEN = "test-access-token";

const ME: Me = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "punter@example.com",
  age_confirmed: true,
  self_excluded_until: null,
  usage: { questions_today: 3, daily_limit: 15, resets_at: "2026-10-08T23:00:00Z" },
};

function ok(data: unknown, meta?: unknown) {
  return HttpResponse.json({ success: true, data, error: null, ...(meta ? { meta } : {}) });
}

function fail(status: number, code: string, message: string, retryAt: string | null = null) {
  return HttpResponse.json(
    { success: false, data: null, error: { code, message, retry_at: retryAt } },
    { status },
  );
}

function makeClient(token: string | null = TOKEN) {
  return createApiClient({ baseUrl: BASE, getAccessToken: async () => token });
}

describe("auth header", () => {
  test("sends the Supabase access token as a bearer token", async () => {
    let auth: string | null = null;
    server.use(
      http.get(`${BASE}/me`, ({ request }) => {
        auth = request.headers.get("Authorization");
        return ok(ME);
      }),
    );

    await makeClient().getMe();

    expect(auth).toBe(`Bearer ${TOKEN}`);
  });

  test("sends no Authorization header when signed out", async () => {
    let hasAuth = true;
    server.use(
      http.get(`${BASE}/fixtures/next`, ({ request }) => {
        hasAuth = request.headers.has("Authorization");
        return ok({ matchweek: 7, fixtures: [], suggested_questions: [] });
      }),
    );

    await makeClient(null).getNextFixtures();

    expect(hasAuth).toBe(false);
  });
});

describe("responses", () => {
  test("unwraps the envelope's data", async () => {
    server.use(http.get(`${BASE}/me`, () => ok(ME)));

    await expect(makeClient().getMe()).resolves.toEqual(ME);
  });

  test("throws an ApiRequestError carrying the server's code, message and retry time", async () => {
    server.use(
      http.post(`${BASE}/me/break`, () =>
        fail(403, "on_break", "You're on a break.", "2026-10-15T14:00:00Z"),
      ),
    );

    const err = await makeClient().takeBreak("7d").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiRequestError);
    expect(err).toMatchObject({
      code: "on_break",
      message: "You're on a break.",
      status: 403,
      retryAt: "2026-10-15T14:00:00Z",
    });
  });

  test("turns a non-JSON error into an internal error", async () => {
    server.use(http.get(`${BASE}/me`, () => new HttpResponse("Bad gateway", { status: 502 })));

    await expect(makeClient().getMe()).rejects.toMatchObject({ code: "internal", status: 502 });
  });

  test("turns a network failure into a connection error", async () => {
    server.use(http.get(`${BASE}/me`, () => HttpResponse.error()));

    await expect(makeClient().getMe()).rejects.toMatchObject({ code: "internal", status: 0 });
  });
});

describe("endpoints", () => {
  test("confirmAge posts both declarations", async () => {
    let body: unknown;
    server.use(
      http.post(`${BASE}/onboarding/age`, async ({ request }) => {
        body = await request.json();
        return ok(ME);
      }),
    );

    await expect(makeClient().confirmAge()).resolves.toEqual(ME);
    expect(body).toEqual({ is_over_18: true, accepts_terms: true });
  });

  test("takeBreak posts the duration", async () => {
    let body: unknown;
    server.use(
      http.post(`${BASE}/me/break`, async ({ request }) => {
        body = await request.json();
        return ok({ ...ME, self_excluded_until: "2026-10-09T14:00:00Z" });
      }),
    );

    const me = await makeClient().takeBreak("24h");

    expect(body).toEqual({ duration: "24h" });
    expect(me.self_excluded_until).toBe("2026-10-09T14:00:00Z");
  });

  test("deleteAccount sends DELETE /me", async () => {
    let called = false;
    server.use(
      http.delete(`${BASE}/me`, () => {
        called = true;
        return ok(null);
      }),
    );

    await expect(makeClient().deleteAccount()).resolves.toBeUndefined();
    expect(called).toBe(true);
  });

  test("listConversations passes the cursor and returns the next one", async () => {
    let url: URL | undefined;
    const conversation = {
      id: "00000000-0000-4000-8000-000000000010",
      title: "Saka away form",
      created_at: "2026-10-07T10:00:00Z",
      updated_at: "2026-10-07T10:05:00Z",
    };
    server.use(
      http.get(`${BASE}/conversations`, ({ request }) => {
        url = new URL(request.url);
        return ok([conversation], { next_cursor: "abc" });
      }),
    );

    const page = await makeClient().listConversations({ cursor: "xyz", limit: 10 });

    expect(url?.searchParams.get("cursor")).toBe("xyz");
    expect(url?.searchParams.get("limit")).toBe("10");
    expect(page).toEqual({ items: [conversation], nextCursor: "abc" });
  });

  test("listConversations reports no next page when meta is absent", async () => {
    server.use(http.get(`${BASE}/conversations`, () => ok([])));

    await expect(makeClient().listConversations()).resolves.toEqual({ items: [], nextCursor: null });
  });

  test("createConversation returns the new conversation", async () => {
    const conversation = {
      id: "00000000-0000-4000-8000-000000000011",
      title: null,
      created_at: "2026-10-07T10:00:00Z",
      updated_at: "2026-10-07T10:00:00Z",
    };
    server.use(http.post(`${BASE}/conversations`, () => ok(conversation)));

    await expect(makeClient().createConversation()).resolves.toEqual(conversation);
  });

  test("listMessages fetches a conversation's messages", async () => {
    const id = "00000000-0000-4000-8000-000000000012";
    const message = {
      id: "00000000-0000-4000-8000-000000000013",
      role: "user",
      content: "Who's injured for Villa vs Spurs?",
      created_at: "2026-10-07T10:00:00Z",
    };
    server.use(http.get(`${BASE}/conversations/${id}/messages`, () => ok([message])));

    await expect(makeClient().listMessages(id)).resolves.toEqual([message]);
  });

  test("getNextFixtures returns the matchweek strip", async () => {
    const data = { matchweek: 7, fixtures: [], suggested_questions: ["Who's injured?"] };
    server.use(http.get(`${BASE}/fixtures/next`, () => ok(data)));

    await expect(makeClient().getNextFixtures()).resolves.toEqual(data);
  });

  test("streamMessage posts the question and yields the answer's events", async () => {
    const id = "00000000-0000-4000-8000-000000000015";
    let body: unknown;
    server.use(
      http.post(`${BASE}/conversations/${id}/messages`, async ({ request }) => {
        body = await request.json();
        return sseResponse([
          { type: "message_start", message_id: "m1", conversation_id: id },
          { type: "text_delta", text: "Hi" },
          { type: "message_end", message_id: "m1", questions_remaining: 14 },
        ]);
      }),
    );

    const events = [];
    for await (const event of await makeClient().streamMessage(id, "Who's injured?")) {
      events.push(event.type);
    }

    expect(body).toEqual({ content: "Who's injured?" });
    expect(events).toEqual(["message_start", "text_delta", "message_end"]);
  });

  test("streamMessage throws before streaming when a gate refuses the question", async () => {
    const id = "00000000-0000-4000-8000-000000000016";
    server.use(
      http.post(`${BASE}/conversations/${id}/messages`, () =>
        fail(429, "daily_limit_reached", "That's today's questions.", "2026-10-08T23:00:00Z"),
      ),
    );

    await expect(makeClient().streamMessage(id, "Any value?")).rejects.toMatchObject({
      code: "daily_limit_reached",
      status: 429,
    });
  });

  test("sendFeedback posts the rating and note", async () => {
    let body: unknown;
    server.use(
      http.post(`${BASE}/feedback`, async ({ request }) => {
        body = await request.json();
        return ok(null);
      }),
    );

    await makeClient().sendFeedback({
      messageId: "00000000-0000-4000-8000-000000000014",
      rating: -1,
      note: "Wrong kick-off time",
    });

    expect(body).toEqual({
      message_id: "00000000-0000-4000-8000-000000000014",
      rating: -1,
      note: "Wrong kick-off time",
    });
  });
});
