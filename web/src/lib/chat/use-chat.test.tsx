import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import type { ApiClient } from "@/lib/api/client";
import { ApiRequestError } from "@/lib/api/errors";
import type { Message, StreamEvent } from "@/lib/api/types";
import { useChat } from "./use-chat";

const CONVERSATION = {
  id: "c1",
  title: null,
  created_at: "2026-10-08T10:00:00Z",
  updated_at: "2026-10-08T10:00:00Z",
};

async function* events(list: StreamEvent[]): AsyncGenerator<StreamEvent> {
  for (const event of list) yield event;
}

const ANSWER: StreamEvent[] = [
  { type: "message_start", message_id: "m1", conversation_id: "c1" },
  { type: "text_delta", text: "Saka has 3 goals away." },
  { type: "sources", sources: [] },
  { type: "message_end", message_id: "m1", questions_remaining: 14 },
];

function fakeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    createConversation: vi.fn().mockResolvedValue(CONVERSATION),
    streamMessage: vi.fn().mockImplementation(async () => events(ANSWER)),
    listMessages: vi.fn().mockResolvedValue([]),
    sendFeedback: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as ApiClient;
}

describe("useChat", () => {
  test("creates a conversation on the first question and streams the answer", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useChat(api));

    await act(() => result.current.ask("How has Saka done away?"));

    expect(api.createConversation).toHaveBeenCalledOnce();
    expect(api.streamMessage).toHaveBeenCalledWith("c1", "How has Saka done away?", expect.any(AbortSignal));
    expect(result.current.conversationId).toBe("c1");
    expect(result.current.items).toMatchObject([
      { kind: "user", content: "How has Saka done away?" },
      { kind: "assistant", answer: { status: "done", text: "Saka has 3 goals away.", messageId: "m1" } },
    ]);
    expect(result.current.questionsRemaining).toBe(14);
  });

  test("reuses the conversation for follow-up questions", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useChat(api));

    await act(() => result.current.ask("First?"));
    await act(() => result.current.ask("Second?"));

    expect(api.createConversation).toHaveBeenCalledOnce();
    expect(result.current.items).toHaveLength(4);
  });

  test("ignores blank questions", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useChat(api));

    await act(() => result.current.ask("   "));

    expect(api.createConversation).not.toHaveBeenCalled();
    expect(result.current.items).toEqual([]);
  });

  test("drops the question and reports the error when a gate refuses it", async () => {
    const refusal = new ApiRequestError({
      code: "daily_limit_reached",
      message: "That's today's questions.",
      status: 429,
    });
    const api = fakeApi({ streamMessage: vi.fn().mockRejectedValue(refusal) });
    const { result } = renderHook(() => useChat(api));

    await act(() => result.current.ask("Any value?"));

    expect(result.current.items).toEqual([]);
    expect(result.current.error).toBe(refusal);
    expect(result.current.isSending).toBe(false);
  });

  test("marks the answer failed when the stream drops part-way", async () => {
    async function* broken(): AsyncGenerator<StreamEvent> {
      yield { type: "message_start", message_id: "m1", conversation_id: "c1" };
      throw new TypeError("network error");
    }
    const api = fakeApi({ streamMessage: vi.fn().mockImplementation(async () => broken()) });
    const { result } = renderHook(() => useChat(api));

    await act(() => result.current.ask("Who's injured?"));

    expect(result.current.items[1]).toMatchObject({
      kind: "assistant",
      answer: { status: "error", error: { code: "internal" } },
    });
  });

  test("loads a past conversation's messages", async () => {
    const messages: Message[] = [
      { id: "u1", role: "user", content: "Who's injured?", created_at: "2026-10-08T10:00:00Z" },
      {
        id: "a1",
        role: "assistant",
        content: "Two players are out.",
        cards: [],
        sources: [],
        feedback: 1,
        created_at: "2026-10-08T10:00:05Z",
      },
    ];
    const api = fakeApi({ listMessages: vi.fn().mockResolvedValue(messages) });
    const { result } = renderHook(() => useChat(api));

    await act(() => result.current.open("c9"));

    expect(api.listMessages).toHaveBeenCalledWith("c9");
    expect(result.current.conversationId).toBe("c9");
    expect(result.current.items).toMatchObject([
      { kind: "user", content: "Who's injured?" },
      { kind: "assistant", feedback: 1, answer: { status: "done", text: "Two players are out.", messageId: "a1" } },
    ]);
  });

  test("starts a fresh chat", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useChat(api));
    await act(() => result.current.ask("First?"));

    act(() => result.current.reset());

    expect(result.current.items).toEqual([]);
    expect(result.current.conversationId).toBeNull();
  });

  test("records feedback straight away and sends it", async () => {
    const api = fakeApi();
    const { result } = renderHook(() => useChat(api));
    await act(() => result.current.ask("First?"));

    await act(() => result.current.rate("m1", -1));

    expect(api.sendFeedback).toHaveBeenCalledWith({ messageId: "m1", rating: -1 });
    expect(result.current.items[1]).toMatchObject({ feedback: -1 });
  });

  test("puts feedback back and reports the error when sending fails", async () => {
    const failure = new ApiRequestError({ code: "internal", message: "Try again.", status: 500 });
    const api = fakeApi({ sendFeedback: vi.fn().mockRejectedValue(failure) });
    const { result } = renderHook(() => useChat(api));
    await act(() => result.current.ask("First?"));

    await act(() => result.current.rate("m1", 1));

    await waitFor(() => expect(result.current.error).toBe(failure));
    expect(result.current.items[1]).toMatchObject({ feedback: null });
  });
});
