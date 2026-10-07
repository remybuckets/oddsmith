# Web lane

You own `web/` only. Read `SPEC.md` ("Chat app UI", "Compliance"), `DECISIONS.md` and `contracts/openapi.yaml` first.

## Build

- Next.js (App Router) + TypeScript strict + Tailwind + shadcn/ui, mobile-first.
- Generate API types from `contracts/openapi.yaml` (e.g. `openapi-typescript`); never hand-write them.
- Screens: Landing, Onboarding (Supabase magic link via supabase-js, then 18+ declaration, then "how it works"), Chat (fixture strip, suggested questions, thread, input), Settings (usage, take-a-break, delete account, help).
- Answer rendering: stream `text_delta` as markdown; render `card` events as stat cards (with W/D/L form strip), odds cards (best price highlighted, ≤4 bookmakers, as-of time) and value badges (coloured only when `is_highlighted`, always "Estimate, not advice."); source line from `sources`; thumbs up/down per answer; `tool_status` as a small "Checking odds…" indicator.
- Handle every `ApiError.code` with a friendly screen or banner (`on_break`, `daily_limit_reached`, `budget_exhausted` = "back tomorrow", etc.).
- Look: dark theme, pitch-green accent, red-card red sparingly (alerts, logo). GamCare (0808 8020 133) and GAMSTOP in footer and settings. Never use "lock", "banker", "guaranteed", "sure thing".

## Rules

- Locally, magic-link emails land in the Supabase inbox at http://127.0.0.1:54324, not a real mailbox.
- Until the backend is merged, run against a mock server that replays contract-shaped SSE streams (e.g. MSW).
- Tests: components with Testing Library; key flows (sign-in → 18+ → ask → see cards) with Playwright.
- Only `NEXT_PUBLIC_*` env vars reach the browser. Never put service-role keys in `web/`.
- Do not touch anything outside `web/`. Need a contract change? Stop and tell the user.
