import type { ApiErrorBody, Card, SourceRef, StreamEvent } from "@/lib/api/types";

export type AnswerStatus = "streaming" | "done" | "error";

/** One assistant answer as it streams in. Every update returns a new object. */
export interface AnswerState {
  messageId: string | null;
  text: string;
  cards: Card[];
  sources: SourceRef[];
  /** The running tool's label, e.g. "Checking odds", or null. */
  activity: string | null;
  status: AnswerStatus;
  error: ApiErrorBody | null;
  questionsRemaining: number | null;
}

export function initialAnswer(): AnswerState {
  return {
    messageId: null,
    text: "",
    cards: [],
    sources: [],
    activity: null,
    status: "streaming",
    error: null,
    questionsRemaining: null,
  };
}

export function applyEvent(state: AnswerState, event: StreamEvent): AnswerState {
  switch (event.type) {
    case "message_start":
      return { ...state, messageId: event.message_id };
    case "tool_status":
      return { ...state, activity: event.status === "started" ? event.label : null };
    case "text_delta":
      return { ...state, text: state.text + event.text };
    case "card":
      return { ...state, cards: [...state.cards, event.card] };
    case "sources":
      return { ...state, sources: event.sources };
    case "message_end":
      return {
        ...state,
        messageId: event.message_id,
        status: "done",
        activity: null,
        questionsRemaining: event.questions_remaining,
      };
    case "error":
      return { ...state, status: "error", activity: null, error: event.error };
  }
}
