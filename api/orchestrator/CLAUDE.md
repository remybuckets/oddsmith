# Orchestrator lane

You own `api/orchestrator/` only. Read `SPEC.md` ("LLM orchestrator"), `oddsmith_tools.json` and `contracts/README.md` first.

## Build

1. `api/orchestrator/tools/`: one module per tool in `oddsmith_tools.json`. Each takes validated input and returns the envelope (`ok`, `source`, `as_of`, `is_stale`, `freshness_limit_hours`, `warnings`, `data`). Parameterised SQL only, against the views `player_match_rows`, `team_match_rows`, `odds_latest` and base tables.
2. Freshness limits: odds 6h, availability 24h, stats/fixtures 48h. `as_of` = oldest `fetched_at` used.
3. `answer()` in `api/orchestrator/__init__.py` exactly as specified in `contracts/README.md`: Claude tool-use loop, max 8 tool calls, stream text once first tool results are back, emit cards built from tool results, then `sources`, then `usage`.
4. System prompt: start from the draft in SPEC.md; keep it in its own file.
5. A CLI (`uv run python -m orchestrator.cli "question"`) to ask questions from the terminal (SPEC day 4).
6. Start an eval set from the six "must answer" questions in SPEC.md; grow it toward 50.

## Rules

- Claude never writes SQL. Tools never call providers — only Postgres (and Voyage for `search_news` query embeddings).
- `compare_to_market`: Poisson from last 10 matches' xG for/against, home-adjusted; label "estimate".
- Tests use `oddsmith_test_orchestrator` with seeded rows (shape from `ingestion/tests/fixtures/` once available). Unit-test tools without Claude; mock Claude in loop tests.
- `api/pyproject.toml` and `uv.lock` are shared with the backend lane: add dependencies with `uv add`; on rebase conflicts, re-run `uv lock`.
- Do not touch anything outside `api/orchestrator/`. Need a tool-schema or DB change? Stop and tell the user.
