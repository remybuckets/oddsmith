import { describe, expect, test } from "vitest";
import type { StreamEvent } from "@/lib/api/types";
import { readEvents } from "./stream";
import { frame, streamOf } from "./test-helpers";

async function collect(body: ReadableStream<Uint8Array>): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of readEvents(body)) {
    events.push(event);
  }
  return events;
}

const START = { type: "message_start", message_id: "m1", conversation_id: "c1" } as const;
const DELTA = { type: "text_delta", text: "Saka has 3 goals away." } as const;

describe("readEvents", () => {
  test("yields each SSE frame as a typed event, in order", async () => {
    const body = streamOf([frame(START) + frame(DELTA)]);

    await expect(collect(body)).resolves.toEqual([START, DELTA]);
  });

  test("reassembles frames split across network chunks", async () => {
    const whole = frame(START) + frame(DELTA);
    const chunks = [whole.slice(0, 7), whole.slice(7, 40), whole.slice(40)];

    await expect(collect(streamOf(chunks))).resolves.toEqual([START, DELTA]);
  });

  test("keeps multi-byte characters intact when split mid-character", async () => {
    const text = frame({ type: "text_delta", text: "Ødegaard — 2 assists" });
    const bytes = new TextEncoder().encode(text);
    const cut = bytes.indexOf(0xc3) + 1;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut));
        controller.enqueue(bytes.slice(cut));
        controller.close();
      },
    });

    await expect(collect(body)).resolves.toEqual([{ type: "text_delta", text: "Ødegaard — 2 assists" }]);
  });

  test("skips event types this app doesn't know yet", async () => {
    const body = streamOf([frame({ type: "heartbeat" }) + frame(DELTA)]);

    await expect(collect(body)).resolves.toEqual([DELTA]);
  });

  test("ends with an internal error when a frame isn't valid JSON", async () => {
    const body = streamOf(["event: text_delta\ndata: {not json\n\n" + frame(DELTA)]);

    const events = await collect(body);

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: "error", error: { code: "internal" } });
  });
});
