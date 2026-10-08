import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { MemberGate } from "@/components/app/member-gate";
import { ApiRequestError } from "@/lib/api/errors";
import type { Fixture, StreamEvent } from "@/lib/api/types";
import { fakeApi, ME, renderWithApp } from "@/test/render";
import { ChatScreen } from "./chat-screen";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const FIXTURE: Fixture = {
  fixture_id: 101,
  matchweek: 7,
  kickoff_at: "2026-10-17T14:00:00Z",
  status: "scheduled",
  home: { id: 1, name: "Newcastle United", short_name: "Newcastle" },
  away: { id: 2, name: "Arsenal", short_name: "Arsenal" },
};

const SOURCE = { source: "API-Football", as_of: "2026-10-10T09:00:00Z", is_stale: false };

const ANSWER: StreamEvent[] = [
  { type: "message_start", message_id: "m1", conversation_id: "c1" },
  { type: "tool_status", tool: "get_player_stats", status: "started", label: "Checking stats" },
  { type: "tool_status", tool: "get_player_stats", status: "finished", label: "Checking stats" },
  { type: "text_delta", text: "Saka has **3 goals** away." },
  {
    type: "card",
    card: { card_type: "stat", title: "Saka — away", columns: ["Stat", "Value"], rows: [["Goals", 3]], source: SOURCE },
  },
  { type: "sources", sources: [SOURCE] },
  { type: "message_end", message_id: "m1", questions_remaining: 14 },
];

async function* events(list: StreamEvent[]): AsyncGenerator<StreamEvent> {
  for (const event of list) yield event;
}

function chatApi(overrides = {}) {
  return fakeApi({
    getNextFixtures: vi.fn().mockResolvedValue({
      matchweek: 7,
      fixtures: [FIXTURE],
      suggested_questions: ["Who's injured for Villa vs Spurs?"],
    }),
    createConversation: vi.fn().mockResolvedValue({
      id: "c1",
      title: null,
      created_at: "2026-10-08T10:00:00Z",
      updated_at: "2026-10-08T10:00:00Z",
    }),
    streamMessage: vi.fn().mockImplementation(async () => events(ANSWER)),
    ...overrides,
  });
}

function renderChat(api = chatApi()) {
  renderWithApp(
    <MemberGate>
      <ChatScreen />
    </MemberGate>,
    { api },
  );
  return api;
}

async function ask(question: string) {
  await userEvent.type(await screen.findByRole("textbox", { name: "Ask Oddsmith" }), question);
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
}

describe("ChatScreen", () => {
  beforeEach(() => router.replace.mockClear());

  test("shows the matchweek's fixtures and asks about one when tapped", async () => {
    const api = renderChat();

    expect(await screen.findByText("Matchweek 7")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Newcastle v Arsenal/ }));

    expect(api.streamMessage).toHaveBeenCalledWith(
      "c1",
      "What do I need to know before Newcastle v Arsenal?",
      expect.any(AbortSignal),
    );
  });

  test("offers suggested questions until the chat starts", async () => {
    const api = renderChat();

    await userEvent.click(await screen.findByRole("button", { name: "Who's injured for Villa vs Spurs?" }));

    expect(api.streamMessage).toHaveBeenCalledWith("c1", "Who's injured for Villa vs Spurs?", expect.any(AbortSignal));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Who's injured for Villa vs Spurs?" })).not.toBeInTheDocument(),
    );
  });

  test("streams the answer with its card, sources and questions left", async () => {
    renderChat();

    await ask("How has Saka done away?");

    expect(await screen.findByText("3 goals")).toBeInTheDocument();
    expect(screen.getByText("How has Saka done away?")).toBeInTheDocument();
    expect(screen.getByText("Saka — away")).toBeInTheDocument();
    expect(screen.getByText(/^Sources: API-Football/)).toBeInTheDocument();
    expect(screen.getByText("14 questions left today")).toBeInTheDocument();
  });

  test("won't send an empty question", async () => {
    renderChat();

    expect(await screen.findByRole("button", { name: "Send" })).toBeDisabled();
  });

  test("shows a 'back tomorrow' banner when the daily limit is reached", async () => {
    const refusal = new ApiRequestError({
      code: "daily_limit_reached",
      message: "You've used today's 15 questions.",
      status: 429,
      retryAt: "2026-10-08T23:00:00Z",
    });
    renderChat(chatApi({ streamMessage: vi.fn().mockRejectedValue(refusal) }));

    await ask("Any value in Newcastle?");

    const banner = await screen.findByRole("alert");
    expect(within(banner).getByText("Back tomorrow")).toBeInTheDocument();
    expect(within(banner).getByText("You've used today's 15 questions.")).toBeInTheDocument();
    expect(within(banner).getByText("Questions reset Fri 9 Oct, 00:00")).toBeInTheDocument();
  });

  test("switches to the break screen when the server says a break is running", async () => {
    const refusal = new ApiRequestError({ code: "on_break", message: "You're on a break.", status: 403 });
    const getMe = vi
      .fn()
      .mockResolvedValueOnce(ME)
      .mockResolvedValue({ ...ME, self_excluded_until: "2099-01-01T12:00:00Z" });
    renderChat(chatApi({ getMe, streamMessage: vi.fn().mockRejectedValue(refusal) }));

    await ask("Any value?");

    expect(await screen.findByRole("heading", { name: "You're on a break" })).toBeInTheDocument();
  });

  test("sends the user to sign in when the session has expired", async () => {
    const expired = new ApiRequestError({ code: "unauthenticated", message: "Please sign in again.", status: 401 });
    renderChat(chatApi({ streamMessage: vi.fn().mockRejectedValue(expired) }));

    await ask("Any value?");

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/sign-in"));
  });

  test("reopens a past chat from the list", async () => {
    const api = chatApi({
      listConversations: vi.fn().mockResolvedValue({
        items: [
          { id: "c7", title: "Saka away form", created_at: "2026-10-07T10:00:00Z", updated_at: "2026-10-07T10:05:00Z" },
        ],
        nextCursor: null,
      }),
      listMessages: vi.fn().mockResolvedValue([
        { id: "u1", role: "user", content: "How has Saka done away?", created_at: "2026-10-07T10:00:00Z" },
        { id: "a1", role: "assistant", content: "Three goals.", created_at: "2026-10-07T10:00:05Z" },
      ]),
    });
    renderChat(api);

    await userEvent.click(await screen.findByRole("button", { name: "Your chats" }));
    await userEvent.click(await screen.findByRole("button", { name: /Saka away form/ }));

    expect(api.listMessages).toHaveBeenCalledWith("c7");
    expect(await screen.findByText("Three goals.")).toBeInTheDocument();
  });

  test("starts a new chat", async () => {
    renderChat();
    await ask("How has Saka done away?");
    await screen.findByText("3 goals");

    await userEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(screen.queryByText("How has Saka done away?")).not.toBeInTheDocument();
  });

  test("links to settings", async () => {
    renderChat();

    expect(await screen.findByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });
});
