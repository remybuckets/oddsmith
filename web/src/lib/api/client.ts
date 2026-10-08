import createClient from "openapi-fetch";
import { readEvents } from "@/lib/chat/stream";
import { fromErrorResponse, fromNetworkFailure } from "./errors";
import type { paths } from "./schema";
import type {
  BreakDuration,
  Conversation,
  FeedbackRating,
  Me,
  Message,
  NextFixtures,
  StreamEvent,
} from "./types";

export interface ApiClientOptions {
  baseUrl: string;
  /** The Supabase access token, or null when signed out. */
  getAccessToken: () => Promise<string | null>;
}

export interface ConversationPage {
  items: Conversation[];
  nextCursor: string | null;
}

export interface FeedbackInput {
  messageId: string;
  rating: FeedbackRating;
  note?: string;
}

interface Envelope<T> {
  data?: T;
  meta?: { next_cursor?: string | null };
}

interface FetchResult<T> {
  data?: Envelope<T>;
  error?: unknown;
  response: Response;
}

/** Runs one request and returns its envelope, or throws an ApiRequestError. */
async function settle<T>(request: () => Promise<FetchResult<T>>): Promise<Envelope<T>> {
  let result: FetchResult<T>;
  try {
    result = await request();
  } catch (cause) {
    throw fromNetworkFailure(cause);
  }
  if (!result.response.ok || result.data === undefined) {
    throw fromErrorResponse(result.response.status, result.error);
  }
  return result.data;
}

/** The envelope's data, which a successful response must include. */
function requireData<T>(envelope: Envelope<T>, status = 200): NonNullable<T> {
  if (envelope.data === undefined || envelope.data === null) {
    throw fromErrorResponse(status, envelope);
  }
  return envelope.data;
}

export function createApiClient({ baseUrl, getAccessToken }: ApiClientOptions) {
  // Look fetch up per call so a mock service worker started after this client still applies.
  const client = createClient<paths>({ baseUrl, fetch: (request) => globalThis.fetch(request) });
  client.use({
    async onRequest({ request }) {
      const token = await getAccessToken();
      if (token) {
        request.headers.set("Authorization", `Bearer ${token}`);
      }
      return request;
    },
  });

  return {
    async getMe(): Promise<Me> {
      return requireData(await settle(() => client.GET("/me")));
    },

    async confirmAge(): Promise<Me> {
      const body = { is_over_18: true, accepts_terms: true } as const;
      return requireData(await settle(() => client.POST("/onboarding/age", { body })));
    },

    async takeBreak(duration: BreakDuration): Promise<Me> {
      return requireData(await settle(() => client.POST("/me/break", { body: { duration } })));
    },

    async deleteAccount(): Promise<void> {
      await settle(() => client.DELETE("/me"));
    },

    async listConversations(
      query: { cursor?: string; limit?: number } = {},
    ): Promise<ConversationPage> {
      const envelope = await settle(() => client.GET("/conversations", { params: { query } }));
      return { items: requireData(envelope), nextCursor: envelope.meta?.next_cursor ?? null };
    },

    async createConversation(): Promise<Conversation> {
      return requireData(await settle(() => client.POST("/conversations")), 201);
    },

    async listMessages(conversationId: string): Promise<Message[]> {
      const params = { path: { id: conversationId } };
      return requireData(await settle(() => client.GET("/conversations/{id}/messages", { params })));
    },

    async getNextFixtures(): Promise<NextFixtures> {
      return requireData(await settle(() => client.GET("/fixtures/next")));
    },

    /**
     * Asks a question. Gate failures (limits, break, budget) throw before streaming starts;
     * failures during the answer arrive as an `error` event.
     */
    async streamMessage(
      conversationId: string,
      content: string,
      signal?: AbortSignal,
    ): Promise<AsyncGenerator<StreamEvent>> {
      let result;
      try {
        result = await client.POST("/conversations/{id}/messages", {
          params: { path: { id: conversationId } },
          body: { content },
          parseAs: "stream",
          signal,
        });
      } catch (cause) {
        throw fromNetworkFailure(cause);
      }
      if (!result.response.ok || !result.data) {
        throw fromErrorResponse(result.response.status, result.error);
      }
      return readEvents(result.data);
    },

    async sendFeedback({ messageId, rating, note }: FeedbackInput): Promise<void> {
      const body = { message_id: messageId, rating, ...(note ? { note } : {}) };
      await settle(() => client.POST("/feedback", { body }));
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
