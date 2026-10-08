// Builders for SSE bodies in tests, shaped like the backend's frames (api/app/chat_stream.py).
type EventLike = { type: string } & Record<string, unknown>;

export function frame(event: EventLike): string {
  return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

export function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
}

export function sseResponse(events: EventLike[]): Response {
  return new Response(streamOf([events.map(frame).join("")]), {
    headers: { "Content-Type": "text/event-stream" },
  });
}
