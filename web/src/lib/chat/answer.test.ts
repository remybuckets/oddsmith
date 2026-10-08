import { describe, expect, test } from "vitest";
import type { Card, SourceRef, StreamEvent } from "@/lib/api/types";
import { applyEvent, initialAnswer } from "./answer";

const SOURCE: SourceRef = { source: "API-Football", as_of: "2026-10-10T09:00:00Z", is_stale: false };
const CARD: Card = {
  card_type: "stat",
  title: "Saka — away, 2026/27",
  columns: ["Stat", "Value"],
  rows: [["Goals", 3]],
  form: "WWDLW",
  source: SOURCE,
};

function run(events: StreamEvent[]) {
  return events.reduce(applyEvent, initialAnswer());
}

describe("applyEvent", () => {
  test("starts streaming with nothing yet", () => {
    expect(initialAnswer()).toMatchObject({ status: "streaming", text: "", cards: [], sources: [] });
  });

  test("records the message id on message_start", () => {
    const state = run([{ type: "message_start", message_id: "m1", conversation_id: "c1" }]);

    expect(state.messageId).toBe("m1");
  });

  test("shows a tool label while it runs and clears it when it finishes", () => {
    const started = run([
      { type: "tool_status", tool: "get_odds", status: "started", label: "Checking odds" },
    ]);
    const finished = applyEvent(started, {
      type: "tool_status",
      tool: "get_odds",
      status: "finished",
      label: "Checking odds",
    });

    expect(started.activity).toBe("Checking odds");
    expect(finished.activity).toBeNull();
  });

  test("appends text deltas", () => {
    const state = run([
      { type: "text_delta", text: "Saka has " },
      { type: "text_delta", text: "3 goals." },
    ]);

    expect(state.text).toBe("Saka has 3 goals.");
  });

  test("collects cards and sources", () => {
    const state = run([
      { type: "card", card: CARD },
      { type: "sources", sources: [SOURCE] },
    ]);

    expect(state.cards).toEqual([CARD]);
    expect(state.sources).toEqual([SOURCE]);
  });

  test("finishes on message_end with the questions left today", () => {
    const state = run([{ type: "message_end", message_id: "m1", questions_remaining: 12 }]);

    expect(state).toMatchObject({ status: "done", questionsRemaining: 12, activity: null });
  });

  test("stops on an error event and keeps the server's message", () => {
    const state = run([
      { type: "tool_status", tool: "get_odds", status: "started", label: "Checking odds" },
      { type: "error", error: { code: "internal", message: "Something went wrong." } },
    ]);

    expect(state).toMatchObject({
      status: "error",
      activity: null,
      error: { code: "internal", message: "Something went wrong." },
    });
  });

  test("never mutates the previous state", () => {
    const before = initialAnswer();

    applyEvent(before, { type: "card", card: CARD });

    expect(before.cards).toEqual([]);
  });
});
