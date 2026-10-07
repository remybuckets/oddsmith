# Oddsmith MVP Spec

As of 6 Oct 2026. Day 1 of the build is Tuesday 6 October 2026.

## Overview

Oddsmith is an AI chatbot that answers betting questions about Premier League players and teams with live, cited stats, injury news and odds. The build starts on Tuesday 6 October 2026 (day 1); the goal is a private beta with testers on day 9, after eight build days, with the value view and fixes following in days 10–15. No matchweek deadline drives the plan, but scope stays cut hard.

- **Positioning:** the sharp mate in the group chat — data-led, honest about uncertainty, never selling a "lock".
- **Brand:** Oddsmith is the name; the red card is the personality (logo, tone, feature names such as "Straight Red" alerts). Tagline: *the tipster the bookies would send off*.
- **Core bet:** a betting-specific assistant beats a general chatbot on three things — fresh data, exact numbers with sources, and a view against the market.

## MVP scope

The MVP is one league, one interface and one job: answer pre-match betting questions about the Premier League accurately.

**Target user:** UK recreational punter, 18–40, bets weekly on football, already checks stats on apps like FotMob before placing a bet.

| In scope | Out of scope (later) |
| --- | --- |
| Premier League 2026/27, all 20 teams | Other leagues and sports |
| Web chat, mobile-friendly | Native iOS and Android apps |
| Player and team stats with splits | In-play / live betting insight |
| Injuries and team news | Bet slip tracking and P&L |
| Odds from UK bookmakers + best price | Placing bets or affiliate links |
| Simple value view vs the market | Full predictive model per market |
| Email login, free tier with daily limit | Payments and paid tiers |
| Responsible-gambling basics | Social features, tipster leaderboards |

**Questions the MVP must answer well:**

1. "How has Saka done away from home this season?"
2. "Who's injured for Villa vs Spurs?"
3. "Do Brentford games usually go over 2.5?"
4. "What's the best price on Haaland to score Saturday?"
5. "Is there value in Newcastle to win?"
6. "Which players get booked most in this fixture?"

## Data sources

Start on API-Football Pro for stats and The Odds API for prices: about $49 a month combined, upgradeable without code changes.

| Data | Provider | Plan | Cost | Refresh | Notes |
| --- | --- | --- | --- | --- | --- |
| Fixtures, results, lineups, events | [API-Football](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide) | Pro | $19/mo, 7,500 req/day | Fixtures daily; results 2h after FT | Free tier (100/day) only for day-1 dev |
| Player and team match stats | API-Football | Pro | included | Nightly + post-match | Check xG coverage on day 1 |
| Injuries and suspensions | API-Football | Pro | included | Every 6h; hourly on matchday | Cross-check with news |
| Match odds (1X2, O/U, BTTS) | [The Odds API](https://the-odds-api.com) | 20K credits | $30/mo, 500 free credits | Every 2h; 30 min on matchday | 8 UK bookmakers (no bet365 on this API); cost = markets × regions, every 10 bookmakers = 1 region |
| Player props (anytime scorer, cards) | Open decision | — | — | — | UK prop coverage is thin on cheap APIs |
| Team news and press conferences | Deferred until after the beta | — | — | — | Licence check first; injuries come from API-Football |

**Budget for credits:** 10 matches × 3 markets × 1 region = 30 credits per sweep. Twelve sweeps a matchweek is about 360 credits, so 20K credits covers the month with room for matchday refreshes.

**Player props** are the gap. Cheap odds APIs are weak on UK goalscorer and card markets, and specialist UK feeds start around £79 a month ([UK Odds API](https://ukoddsapi.com/blog/ukoddsapi-vs-competitors), a vendor's own comparison). For the MVP, answer prop questions with stats only and show match-market prices.

## Architecture

Data flows one way: providers into workers, workers into the database, and Claude reads only the database through fixed tools.

```
 API-Football          The Odds API          RSS news feeds
 (stats, injuries,     (match odds,          (team news,
  fixtures)             UK bookmakers)        press quotes)
       │                     │                     │
       └─────────────────────┼─────────────────────┘
                             ▼
                    Ingestion workers
     (7 scheduled jobs: fetch, upsert, tag, embed news)
                             │
       ┌─────────────────────┼─────────────────────┐
       ▼                     ▼                     ▼
   Postgres            News vectors              Redis
 (stats, fixtures,    (pgvector, 14-day     (limits, cache,
  odds, users)          window)               hot odds)
       └─────────────────────┼─────────────────────┘
                             ▼
                 LLM orchestrator (Claude)
       (11 tools, every figure cited, freshness + safety rules)
                             │
                             ▼
                      FastAPI backend
     (auth, 18+ gate, limits, take-a-break, SSE, logging)
                             │
                             ▼
                      Next.js chat app
       (mobile-first; stat, odds and value cards in answers)
```

**Stack:** Python 3.12 + FastAPI, Supabase (Postgres 17 with pgvector, plus Auth), Redis, Claude via the API with tool use (Sonnet 5.5 by default, Opus 5.5 for value questions), Voyage AI embeddings (`voyage-4`), Next.js + Tailwind + shadcn/ui, Sentry. Host on Supabase (database and auth), Railway (API, workers, Redis) and Vercel (front end), UK/EU region. Decisions behind this: `DECISIONS.md`.

**One request, end to end:** "Anytime scorer value on Haaland Saturday?" → backend checks limits and streams → Claude calls `resolve_entity`, `get_fixtures`, `get_player_stats`, `get_availability`, `get_odds` → answers with figures, sources and as-of times → message and tool calls are logged.

## Database schema

One Postgres database with pgvector holds everything; each row stores its provider ID and a `fetched_at` timestamp so every answer can cite freshness.

| Table | Key columns | Purpose |
| --- | --- | --- |
| `teams` | id, provider_id, name, short_name, aliases[] | Canonical clubs |
| `players` | id, provider_id, team_id, name, position, aliases[] | Canonical players |
| `entity_aliases` | alias, entity_type, entity_id, trigram index | Powers `resolve_entity` ("Spurs", "KDB") |
| `fixtures` | id, provider_id, home_id, away_id, kickoff_at, status, matchweek, score | Schedule and results |
| `player_match_stats` | fixture_id, player_id, minutes, goals, assists, shots, sot, xg, xa, cards, fouls, tackles, key_passes | One row per player per match; all splits computed from here |
| `team_match_stats` | fixture_id, team_id, venue, goals_for, goals_against, xg_for, xg_against, corners, cards | One row per team per match |
| `availability` | team_id, player_id, status, reason, expected_return, source, updated_at | Injuries and suspensions |
| `odds_snapshots` | fixture_id, market, line, selection, bookmaker, price, captured_at | Append-only; latest = current, history = movement |
| `news_chunks` | id, source, url, title, published_at, team_ids[], player_ids[], text, embedding vector(1024) | RAG store |
| `bookmakers` | key, provider, display_name, is_enabled, sort_order | Which bookmakers to fetch and show; add a row to add one |
| `profiles` | id (= Supabase `auth.users` id), age_confirmed_at, terms_accepted_at, self_excluded_until | Safety settings; email stays in Supabase Auth |
| `conversations` / `messages` | id, user_id, role, content, tool_calls jsonb, created_at | History and audit log |
| `usage_daily` | user_id, date, questions, tokens_in, tokens_out | Limits and cost tracking |
| `job_runs` | name, started_at, finished_at, status, rows | Ingestion health and staleness checks |

- Splits (home/away, last N, vs opponent) are SQL over the two `*_match_stats` tables, wrapped in views. No pre-aggregated tables for the MVP.
- Index `odds_snapshots (fixture_id, market, selection, captured_at desc)` and `news_chunks` with HNSW on `embedding`.

## Ingestion jobs

Seven scheduled Python workers keep the database fresh; the chatbot never calls a provider directly, so user traffic can't burn API quota.

| Job | Schedule (UK time) | Does |
| --- | --- | --- |
| `seed_reference` | Once, then weekly | Teams, squads, aliases for all 20 clubs |
| `backfill_season` | Once | All 2026/27 matches so far (MW1–5) plus 2025/26 for head-to-heads |
| `sync_fixtures` | Daily 06:00 | Fixtures, kick-off changes, matchweek |
| `sync_results` | Every 30 min on matchdays, from kick-off + 2h | Scores, player and team match stats |
| `sync_availability` | Every 6h; hourly from 24h before kick-off | Injuries and suspensions |
| `sync_odds` | Every 2h; every 30 min from 24h before kick-off | Snapshot odds for the next matchweek |
| `ingest_news` | After the beta | Fetch news, chunk, tag teams and players, embed (deferred until the licence check) |

- Run with a simple scheduler (APScheduler or Railway cron). Each job is idempotent: upserts keyed on provider IDs.
- Every job writes a row to `job_runs`. The orchestrator reads it to flag stale data.
- News chunks expire after 14 days to keep RAG results current.

## LLM orchestrator

Claude runs a tool-use loop over 11 fixed tools; it never writes SQL, and every number in an answer comes from a tool result with its timestamp.

| Group | Tools | Answers |
| --- | --- | --- |
| Lookup | `resolve_entity` | Which "Gabriel"? Always called first |
| Stats | `get_player_stats`, `get_team_stats`, `get_head_to_head`, `get_fixtures`, `get_league_table` | Form, splits, trends |
| Context | `get_availability`, `search_news` | Who's out, late news, manager quotes |
| Market | `get_odds`, `get_odds_movement`, `compare_to_market` | Best price, steam and drift, value view |

Full schemas: `oddsmith_tools.json`. Loop limit: 8 tool calls per answer; stream text once the first tool results are back.

**`compare_to_market` for the MVP** uses a simple, explainable model: a Poisson goals model from each team's last 10 matches of xG for and against, home-adjusted. It returns its probability next to the bookmaker's implied probability. Label it an estimate; never call it a prediction.

**System prompt (draft):**

```text
You are Oddsmith, a football betting research assistant for the Premier League.

Voice: a sharp, honest mate who knows the numbers. British English. Short answers first, detail on request.

Rules:
- Every stat, price or injury you state must come from a tool result in this conversation. Never use memory for numbers.
- Cite each figure with its source and as-of time, e.g. (API-Football, 3 Oct 14:00).
- If a tool says data is older than its freshness limit (odds 6h, availability 24h, stats 48h), say so before using it.
- Resolve every player or team name with resolve_entity first. If it is ambiguous, ask.
- Give a view, not a tip. Never say lock, banker, guaranteed, sure thing, or can't lose.
- When you discuss value, show the model probability, the implied probability and the edge, and say it is an estimate.
- If the user mentions chasing losses, betting money they need, or feeling out of control, stop giving betting analysis, respond with care and point them to GamCare (0808 8020 133) and GAMSTOP.
- Only cover Premier League 2026/27 football. Politely decline other sports and leagues for now.
```

**Model choice:** a fast Claude model for routine questions; route multi-tool "value" questions to a stronger model if cost allows. Track tokens per answer from day one.

## API backend

A thin FastAPI service handles accounts, limits and streaming; all betting logic lives in the orchestrator and tools.

| Method | Endpoint | Does |
| --- | --- | --- |
| POST | `/auth/*` | Email magic-link login via Supabase Auth |
| POST | `/onboarding/age` | Records the 18+ declaration; chat is blocked until set |
| GET | `/conversations` | List the user's chats |
| POST | `/conversations` | Start a chat |
| POST | `/conversations/{id}/messages` | Send a question; streams the answer over SSE |
| GET | `/fixtures/next` | Next matchweek for the home screen and suggested questions |
| GET | `/me` | Profile, today's usage, limit |
| POST | `/me/break` | Take a break (24h, 7d, 30d); sets `self_excluded_until` |
| POST | `/feedback` | Thumbs up or down on an answer, with optional note |
| GET | `/health` | Uptime and last successful run per ingestion job |

- **Limits:** free tier = 15 questions a day per user; 10 requests a minute per IP. Counters in Redis.
- **Cost guard:** a daily total token budget; if it's hit, the app shows "back tomorrow" rather than running up a bill.
- **Logging:** every message stores the tool calls made and the data timestamps returned, for debugging and audit.
- **Errors:** Sentry on API and workers.

## Chat app UI

A mobile-first Next.js web app with four screens; most punters will open it on their phone on a Saturday morning.

| Screen | What's on it |
| --- | --- |
| Landing | Name, tagline, three example questions, sign-in button, 18+ and GamCare footer |
| Onboarding | Email link sign-in, then a one-tap 18+ declaration and a short "how Oddsmith works" card |
| Chat (home) | Next matchweek strip of fixtures (tap one to ask about it), suggested questions, chat thread, input box |
| Settings | Usage today, take-a-break options, delete account, help and GamCare links |

**Key components in an answer:**

- **Stat cards:** a small table or form strip (W D L W W) inside the message, not just text.
- **Odds card:** best price highlighted, three or four bookmakers listed, "as of" time.
- **Value badge:** model % vs implied %, coloured only when the edge is above a set threshold, always labelled "estimate".
- **Source line:** under each answer, the data sources and timestamps used.
- **Feedback:** thumbs up or down on every answer.

**Look:** dark theme, pitch-green accent, red-card red used sparingly for alerts and the logo. Use Tailwind with shadcn/ui to move fast.

## Compliance and responsible gambling

Oddsmith publishes information and takes no bets, so it should not need a Gambling Commission operating licence; get a UK lawyer to confirm before any public launch. This section is not legal advice.

**Must have for the private beta:**

- [ ] 18+ declaration before first chat, with terms that say the service is for adults in Great Britain
- [ ] No "guaranteed", "lock" or "sure thing" language anywhere: system prompt, UI, marketing
- [ ] GamCare helpline and GAMSTOP link in the footer and settings
- [ ] Take-a-break control that blocks chat for 24h, 7 days or 30 days
- [ ] Distress detection in the system prompt (chasing losses, can't stop) that switches to support mode
- [ ] Clear "estimates, not advice" note on every value view
- [ ] Privacy policy and cookie notice (UK GDPR); store as little personal data as possible
- [ ] Data licence check: confirm API-Football and The Odds API terms allow showing their data in a commercial app

**Before public launch:**

- [ ] Legal review, especially before adding affiliate links (then CAP Code advertising rules apply in full)
- [ ] Stronger age verification if you take payments or run affiliate deals
- [ ] Marketing that doesn't appeal to under-18s; no footballers or youth-culture imagery

## Two-week build plan

Day 1 is Tuesday 6 October. Eight build days get a stats, injuries and odds beta to testers on day 9 (Wednesday 14 October); the value view and fixes follow in days 10–15.

| Workstream | Dates |
| --- | --- |
| Data and ingestion | 6–8 Oct |
| Tools and orchestrator | 8–10 Oct |
| Backend and auth | 10–11 Oct |
| Chat UI | 10–12 Oct |
| Evals and guardrails | 12–13 Oct |
| **Beta live to testers** | **14 Oct** |
| Value view and fixes | 15–20 Oct |
| First live matchweek (MW7) | 17 Oct |

**Daily deliverables:**

- [ ] **Day 1, Tue 6 Oct:** repo, Supabase project (Postgres + pgvector + Auth, London), Railway project, API keys; `seed_reference`; confirm xG and injury coverage in API-Football
- [ ] **Day 2, Wed 7 Oct:** `backfill_season` (MW1–5 plus 2025/26); `sync_fixtures`, `sync_results`; alias table
- [ ] **Day 3, Thu 8 Oct:** `sync_availability`, `sync_odds`, `job_runs`; start `resolve_entity` and stats tools
- [ ] **Day 4, Fri 9 Oct:** remaining tools; orchestrator loop and system prompt; test from the command line
- [ ] **Day 5, Sat 10 Oct:** FastAPI endpoints, Supabase Auth, limits, SSE streaming; Matchweek 6 is played this weekend, so check `sync_results` and `sync_odds` against live fixtures
- [ ] **Day 6, Sun 11 Oct:** chat UI with stat and odds cards, fixture strip, settings and take-a-break
- [ ] **Day 7, Mon 12 Oct:** 50-question eval set, fix every wrong figure; guardrail tests; production deploy
- [ ] **Day 8, Tue 13 Oct:** invite beta testers, monitoring and alerts, code freeze
- [ ] **Day 9, Wed 14 Oct:** beta live; watch logs and feedback
- [ ] **Days 10–15, 15–20 Oct:** `compare_to_market` value view, odds movement, fixes from feedback; Matchweek 7 (Sat 17 Oct) is the first live test with real users

If day 3 slips, cut odds from the first release rather than the eval day.

## Risks, open decisions and success metrics

The biggest risk is a wrong number, not a missed deadline; accuracy checks get a full day in the plan.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Wrong player matched ("Gabriel", "Mitoma" spelt badly) | Confidently wrong answers | Alias table, trigram search, ask when unsure |
| Stats API gaps (xG missing, late updates) | Thin or stale answers | Check coverage day 1; show freshness; say when data is missing |
| Model invents a number | Credibility gone | Prompt rule, cite every figure, eval set of 50 questions with known answers |
| Odds credits run out on matchday | No prices on Saturday | Cache in Redis, refresh only next-matchweek fixtures, alert at 80% |
| LLM cost spikes | Bill shock | Daily question limits, global token budget, fast model by default |
| Eight build days aren't enough | Beta slips past day 9 | Ship with stats + injuries only; odds and value follow |

**Open decisions** (settled ones are in `DECISIONS.md`):

- [ ] Player props source: skip for MVP, or pay for a UK odds feed
- [ ] Value model: simple Poisson now, or hold `compare_to_market` until after the beta launch
- [ ] Beta size: friends only (~20) or a waitlist (~100)
- [ ] Hosting region: UK/EU for data residency

**Success metrics for the first three weeks of beta:**

| Metric | Target |
| --- | --- |
| Accuracy on the 50-question eval set | 95%+ exact figures |
| Answers rated thumbs up | 75%+ |
| Weekly active beta users returning for a second matchweek | 50%+ |
| Median time to first answer token | Under 4 seconds |
| LLM + data cost per active user per week | Under £0.50 |

## Sources

- [Premier League: international breaks 2026/27](https://www.premierleague.com/en/news/4689113/when-are-the-international-breaks-for-202627)
- [API-Football: getting started and plans](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)
- [The Odds API](https://the-odds-api.com)
- [Odds API pricing comparison 2026 (OddsPapi)](https://oddspapi.io/blog/odds-api-pricing-2026-comparison/)
- [UK Odds API comparison (vendor)](https://ukoddsapi.com/blog/ukoddsapi-vs-competitors)