import { createParser } from "eventsource-parser";
import { INTERNAL_MESSAGE } from "@/lib/api/errors";
import type { StreamEvent } from "@/lib/api/types";

const KNOWN_TYPES: ReadonlySet<string> = new Set<StreamEvent["type"]>([
  "message_start",
  "tool_status",
  "text_delta",
  "card",
  "sources",
  "message_end",
  "error",
]);

const MALFORMED: StreamEvent = { type: "error", error: { code: "internal", message: INTERNAL_MESSAGE } };

function isStreamEvent(value: unknown): value is StreamEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    typeof value.type === "string" &&
    KNOWN_TYPES.has(value.type)
  );
}

function parseData(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return MALFORMED;
  }
}

/**
 * Turns a SendMessage SSE body into contract events. Unknown event types are skipped so the
 * backend can add new ones; a frame that isn't JSON ends the stream with an internal error.
 */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const frames: string[] = [];
  const parser = createParser({ onEvent: (message) => frames.push(message.data) });
  const decoder = new TextDecoder();
  const reader = body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) return;
      parser.feed(decoder.decode(value, { stream: true }));
      for (const data of frames.splice(0)) {
        const event = parseData(data);
        if (event === MALFORMED) {
          yield MALFORMED;
          return;
        }
        if (isStreamEvent(event)) yield event;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
