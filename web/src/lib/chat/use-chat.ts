"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiClient } from "@/lib/api/client";
import { ApiRequestError, asApiError } from "@/lib/api/errors";
import type { FeedbackRating, Message, StreamEvent } from "@/lib/api/types";
import { type AnswerState, applyEvent, initialAnswer } from "./answer";

export const CUT_OFF_MESSAGE = "The answer was cut off. Please ask again.";

export type ChatItem =
  | { kind: "user"; id: string; content: string }
  | { kind: "assistant"; id: string; answer: AnswerState; feedback: FeedbackRating | null };

/** Saved messages as thread items; assistant messages are complete answers. */
export function fromMessages(messages: Message[]): ChatItem[] {
  return messages.map((message) =>
    message.role === "user"
      ? { kind: "user", id: message.id, content: message.content }
      : {
          kind: "assistant",
          id: message.id,
          feedback: message.feedback ?? null,
          answer: {
            ...initialAnswer(),
            messageId: message.id,
            text: message.content,
            cards: message.cards ?? [],
            sources: message.sources ?? [],
            status: "done",
          },
        },
  );
}

export function useChat(api: ApiClient) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [questionsRemaining, setQuestionsRemaining] = useState<number | null>(null);
  // Refs, not state, so a double tap can't start two requests before React re-renders.
  const inFlight = useRef<AbortController | null>(null);
  const currentConversation = useRef<string | null>(null);

  useEffect(() => () => inFlight.current?.abort(), []);

  const updateAnswer = useCallback((itemId: string, event: StreamEvent) => {
    setItems((previous) =>
      previous.map((item) =>
        item.kind === "assistant" && item.id === itemId
          ? { ...item, answer: applyEvent(item.answer, event) }
          : item,
      ),
    );
  }, []);

  const ask = useCallback(
    async (rawQuestion: string) => {
      const question = rawQuestion.trim();
      if (!question || inFlight.current) return;
      const controller = new AbortController();
      inFlight.current = controller;
      const userItemId = crypto.randomUUID();
      const answerItemId = crypto.randomUUID();
      let hasStarted = false;
      setError(null);
      setIsSending(true);
      setItems((previous) => [
        ...previous,
        { kind: "user", id: userItemId, content: question },
        { kind: "assistant", id: answerItemId, answer: initialAnswer(), feedback: null },
      ]);
      try {
        const id = currentConversation.current ?? (await api.createConversation()).id;
        currentConversation.current = id;
        setConversationId(id);
        const stream = await api.streamMessage(id, question, controller.signal);
        hasStarted = true;
        for await (const event of stream) {
          updateAnswer(answerItemId, event);
          if (event.type === "message_end") setQuestionsRemaining(event.questions_remaining);
        }
      } catch (cause) {
        if (hasStarted) {
          const message = cause instanceof ApiRequestError ? cause.message : CUT_OFF_MESSAGE;
          updateAnswer(answerItemId, { type: "error", error: { code: "internal", message } });
        } else {
          setItems((previous) => previous.filter((item) => item.id !== userItemId && item.id !== answerItemId));
          setError(asApiError(cause));
        }
      } finally {
        inFlight.current = null;
        setIsSending(false);
      }
    },
    [api, updateAnswer],
  );

  const reset = useCallback(() => {
    inFlight.current?.abort();
    currentConversation.current = null;
    setConversationId(null);
    setItems([]);
    setError(null);
  }, []);

  const open = useCallback(
    async (id: string) => {
      reset();
      currentConversation.current = id;
      setConversationId(id);
      try {
        setItems(fromMessages(await api.listMessages(id)));
      } catch (cause) {
        setError(asApiError(cause));
      }
    },
    [api, reset],
  );

  const setFeedback = useCallback((messageId: string, feedback: FeedbackRating | null) => {
    setItems((previous) =>
      previous.map((item) =>
        item.kind === "assistant" && item.answer.messageId === messageId ? { ...item, feedback } : item,
      ),
    );
  }, []);

  const rate = useCallback(
    async (messageId: string, rating: FeedbackRating) => {
      const target = items.find((item) => item.kind === "assistant" && item.answer.messageId === messageId);
      const previous = target?.kind === "assistant" ? target.feedback : null;
      setFeedback(messageId, rating);
      try {
        await api.sendFeedback({ messageId, rating });
      } catch (cause) {
        setFeedback(messageId, previous);
        setError(asApiError(cause));
      }
    },
    [api, items, setFeedback],
  );

  const dismissError = useCallback(() => setError(null), []);

  return {
    conversationId,
    items,
    isSending,
    error,
    questionsRemaining,
    ask,
    open,
    reset,
    rate,
    dismissError,
  };
}

export type ChatController = ReturnType<typeof useChat>;
