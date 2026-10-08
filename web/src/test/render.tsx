import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";
import { AppContext, type AppServices, type AuthState } from "@/components/app/app-context";
import type { ApiClient } from "@/lib/api/client";
import type { Me } from "@/lib/api/types";

export const ME: Me = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "punter@example.com",
  age_confirmed: true,
  self_excluded_until: null,
  usage: { questions_today: 3, daily_limit: 15, resets_at: "2026-10-08T23:00:00Z" },
};

export function fakeAuth(overrides: Partial<AuthState> = {}): AuthState {
  return {
    session: { accessToken: "token", email: ME.email },
    isLoading: false,
    sendMagicLink: vi.fn().mockResolvedValue(undefined),
    signOut: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

export function fakeApi(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    getMe: vi.fn().mockResolvedValue(ME),
    confirmAge: vi.fn().mockResolvedValue(ME),
    takeBreak: vi.fn().mockResolvedValue(ME),
    deleteAccount: vi.fn().mockResolvedValue(undefined),
    listConversations: vi.fn().mockResolvedValue({ items: [], nextCursor: null }),
    createConversation: vi.fn(),
    listMessages: vi.fn().mockResolvedValue([]),
    getNextFixtures: vi.fn().mockResolvedValue({ matchweek: 7, fixtures: [], suggested_questions: [] }),
    streamMessage: vi.fn(),
    sendFeedback: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as ApiClient;
}

export function renderWithApp(ui: ReactElement, services: Partial<AppServices> = {}) {
  const value: AppServices = { api: fakeApi(), auth: fakeAuth(), ...services };
  return { ...render(<AppContext.Provider value={value}>{ui}</AppContext.Provider>), services: value };
}
