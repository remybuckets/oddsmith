# Orchestrator lane

You own `api/orchestrator/` only. Read `SPEC.md` ("LLM orchestrator"), `DECISIONS.md`, `oddsmith_tools.json` and `contracts/README.md` first.

## Build

1. `api/orchestrator/tools/`: one module per tool in `oddsmith_tools.json`. Each takes validated input and returns the envelope (`ok`, `source`, `as_of`, `is_stale`, `freshness_limit_hours`, `warnings`, `data`). Parameterised SQL only, against the views `player_match_rows`, `team_match_rows`, `odds_latest` and base tables.
2. Freshness limits: odds 6h, availability 24h, stats/fixtures 48h. `as_of` = oldest `fetched_at` used.
3. `answer()` in `api/orchestrator/__init__.py` exactly as specified in `contracts/README.md`: Claude tool-use loop, max 8 tool calls, stream text once first tool results are back, emit cards built from tool results, then `sources`, then `usage`.
4. System prompt: start from the draft in SPEC.md; keep it in its own file.
5. Models: `CLAUDE_MODEL_FAST` (Sonnet 5.5) by default; `CLAUDE_MODEL_STRONG` (Opus 5.5) for value questions. Decide the route before the loop starts (switching model mid-loop loses the prompt cache). Cache the system prompt and tool list. Log tokens per answer from day one.
6. A CLI (`uv run python -m orchestrator.cli "question"`) to ask questions from the terminal (SPEC day 4).
7. Start an eval set from the six "must answer" questions in SPEC.md; grow it toward 50.

## Rules

- Claude never writes SQL. Tools never call providers, only Postgres.
- News is off for the beta: don't offer `search_news` to Claude while `NEWS_ENABLED=false`.
- Odds tools use enabled bookmakers only and label them with `bookmakers.display_name`.
- `compare_to_market`: Poisson from last 10 matches' xG for/against, home-adjusted; label "estimate".
- Tests use the database printed by `db/test-db.sh orchestrator` with seeded rows (shape from `ingestion/tests/fixtures/` once available). Unit-test tools without Claude; mock Claude in loop tests.
- `api/pyproject.toml` and `uv.lock` are shared with the backend lane: add dependencies with `uv add`; on rebase conflicts, re-run `uv lock`.
- Do not touch anything outside `api/orchestrator/`. Need a tool-schema or DB change? Stop and tell the user.
