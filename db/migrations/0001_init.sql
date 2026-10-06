-- 0001_init: full MVP schema (see SPEC.md "Database schema").
-- Owned by the lead lane. Other lanes request changes; never edit an applied migration — add a new one.
--
-- Users live in Supabase (auth + profile). Every user_id here is the Supabase Auth user id;
-- there is deliberately no users table and no FK to it. Account deletion must delete rows here too.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------------------

CREATE TABLE teams (
    id          bigserial PRIMARY KEY,
    provider_id integer     NOT NULL UNIQUE,             -- API-Football team id
    name        text        NOT NULL,
    short_name  text        NOT NULL,
    aliases     text[]      NOT NULL DEFAULT '{}',
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE players (
    id          bigserial PRIMARY KEY,
    provider_id integer     NOT NULL UNIQUE,             -- API-Football player id
    team_id     bigint      REFERENCES teams (id),       -- current club; NULL if left the league
    name        text        NOT NULL,
    position    text        CHECK (position IN ('GK', 'DEF', 'MID', 'FWD')),
    aliases     text[]      NOT NULL DEFAULT '{}',
    fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX players_team_id_idx ON players (team_id);

-- Powers resolve_entity. alias_search is lowercased and accent-stripped by ingestion
-- ("Ødegaard" -> "odegaard") so the trigram index can stay on a plain column.
CREATE TABLE entity_aliases (
    id           bigserial PRIMARY KEY,
    alias        text   NOT NULL,
    alias_search text   NOT NULL,
    entity_type  text   NOT NULL CHECK (entity_type IN ('team', 'player')),
    entity_id    bigint NOT NULL,
    UNIQUE (alias_search, entity_type, entity_id)
);
CREATE INDEX entity_aliases_trgm_idx ON entity_aliases USING gin (alias_search gin_trgm_ops);

-- ---------------------------------------------------------------------------
-- Matches and stats
-- ---------------------------------------------------------------------------

CREATE TABLE fixtures (
    id          bigserial PRIMARY KEY,
    provider_id integer     NOT NULL UNIQUE,
    season      text        NOT NULL CHECK (season ~ '^\d{4}/\d{2}$'),   -- '2026/27'
    matchweek   smallint    CHECK (matchweek BETWEEN 1 AND 38),
    home_id     bigint      NOT NULL REFERENCES teams (id),
    away_id     bigint      NOT NULL REFERENCES teams (id),
    kickoff_at  timestamptz NOT NULL,
    status      text        NOT NULL
                CHECK (status IN ('scheduled', 'live', 'finished', 'postponed', 'cancelled')),
    home_score  smallint,
    away_score  smallint,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (home_id <> away_id)
);
CREATE INDEX fixtures_kickoff_idx   ON fixtures (kickoff_at);
CREATE INDEX fixtures_matchweek_idx ON fixtures (season, matchweek);
CREATE INDEX fixtures_home_idx      ON fixtures (home_id, kickoff_at DESC);
CREATE INDEX fixtures_away_idx      ON fixtures (away_id, kickoff_at DESC);

-- One row per player per match. team_id is the player's club in that match (transfers).
CREATE TABLE player_match_stats (
    fixture_id      bigint       NOT NULL REFERENCES fixtures (id) ON DELETE CASCADE,
    player_id       bigint       NOT NULL REFERENCES players (id),
    team_id         bigint       NOT NULL REFERENCES teams (id),
    minutes         smallint     NOT NULL DEFAULT 0,
    goals           smallint     NOT NULL DEFAULT 0,
    assists         smallint     NOT NULL DEFAULT 0,
    shots           smallint     NOT NULL DEFAULT 0,
    shots_on_target smallint     NOT NULL DEFAULT 0,
    xg              numeric(5,2),                        -- NULL = provider has no xG
    xa              numeric(5,2),
    yellow_cards    smallint     NOT NULL DEFAULT 0,
    red_cards       smallint     NOT NULL DEFAULT 0,
    fouls           smallint     NOT NULL DEFAULT 0,
    tackles         smallint     NOT NULL DEFAULT 0,
    key_passes      smallint     NOT NULL DEFAULT 0,
    fetched_at      timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (fixture_id, player_id)
);
CREATE INDEX player_match_stats_player_idx ON player_match_stats (player_id);

CREATE TABLE team_match_stats (
    fixture_id    bigint      NOT NULL REFERENCES fixtures (id) ON DELETE CASCADE,
    team_id       bigint      NOT NULL REFERENCES teams (id),
    venue         text        NOT NULL CHECK (venue IN ('home', 'away')),
    goals_for     smallint    NOT NULL,
    goals_against smallint    NOT NULL,
    xg_for        numeric(5,2),
    xg_against    numeric(5,2),
    corners       smallint,
    yellow_cards  smallint    NOT NULL DEFAULT 0,
    red_cards     smallint    NOT NULL DEFAULT 0,
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fixture_id, team_id)
);
CREATE INDEX team_match_stats_team_idx ON team_match_stats (team_id);

-- Current injuries and suspensions. Ingestion deletes rows for players who are fit again.
CREATE TABLE availability (
    id              bigserial PRIMARY KEY,
    team_id         bigint      NOT NULL REFERENCES teams (id),
    player_id       bigint      NOT NULL REFERENCES players (id),
    status          text        NOT NULL CHECK (status IN ('injured', 'suspended', 'doubtful')),
    reason          text,
    expected_return date,
    source          text        NOT NULL,                -- 'api-football' | news source name
    updated_at      timestamptz NOT NULL,                -- when the source last changed it
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (player_id, source)
);
CREATE INDEX availability_team_idx ON availability (team_id);

-- ---------------------------------------------------------------------------
-- Odds (append-only)
-- ---------------------------------------------------------------------------

CREATE TABLE odds_snapshots (
    id          bigserial PRIMARY KEY,
    fixture_id  bigint       NOT NULL REFERENCES fixtures (id) ON DELETE CASCADE,
    market      text         NOT NULL CHECK (market IN ('h2h', 'totals', 'btts')),
    line        numeric(4,2),                            -- totals only, e.g. 2.5
    selection   text         NOT NULL
                CHECK (selection IN ('home', 'draw', 'away', 'over', 'under', 'yes', 'no')),
    bookmaker   text         NOT NULL,                   -- The Odds API bookmaker key
    price       numeric(7,3) NOT NULL CHECK (price > 1), -- decimal odds
    captured_at timestamptz  NOT NULL,
    UNIQUE NULLS NOT DISTINCT (fixture_id, market, line, selection, bookmaker, captured_at)
);
CREATE INDEX odds_snapshots_lookup_idx
    ON odds_snapshots (fixture_id, market, selection, captured_at DESC);

-- ---------------------------------------------------------------------------
-- News RAG store (14-day window, enforced by ingest_news)
-- ---------------------------------------------------------------------------

CREATE TABLE news_chunks (
    id           bigserial PRIMARY KEY,
    source       text         NOT NULL,
    url          text         NOT NULL,
    title        text         NOT NULL,
    published_at timestamptz  NOT NULL,
    chunk_index  smallint     NOT NULL DEFAULT 0,
    team_ids     bigint[]     NOT NULL DEFAULT '{}',
    player_ids   bigint[]     NOT NULL DEFAULT '{}',
    text         text         NOT NULL,                  -- headline + summary only, never full articles
    embedding    vector(1024),                           -- Voyage AI, 1024 dims
    fetched_at   timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (url, chunk_index)
);
CREATE INDEX news_chunks_embedding_idx  ON news_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX news_chunks_published_idx  ON news_chunks (published_at DESC);
CREATE INDEX news_chunks_team_ids_idx   ON news_chunks USING gin (team_ids);
CREATE INDEX news_chunks_player_ids_idx ON news_chunks USING gin (player_ids);

-- ---------------------------------------------------------------------------
-- Chat and usage (user_id = Supabase Auth user id)
-- ---------------------------------------------------------------------------

CREATE TABLE conversations (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid        NOT NULL,
    title      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_user_idx ON conversations (user_id, updated_at DESC);

-- tool_calls: [{tool, input, source, as_of, is_stale, duration_ms, error}] — the audit log.
CREATE TABLE messages (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid        NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role            text        NOT NULL CHECK (role IN ('user', 'assistant')),
    content         text        NOT NULL,
    tool_calls      jsonb       NOT NULL DEFAULT '[]',
    model           text,
    tokens_in       integer,
    tokens_out      integer,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_conversation_idx ON messages (conversation_id, created_at);

CREATE TABLE feedback (
    id         bigserial   PRIMARY KEY,
    message_id uuid        NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    user_id    uuid        NOT NULL,
    rating     smallint    NOT NULL CHECK (rating IN (-1, 1)),
    note       text        CHECK (char_length(note) <= 1000),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (message_id, user_id)
);

CREATE TABLE usage_daily (
    user_id    uuid    NOT NULL,
    date       date    NOT NULL,                         -- UK calendar date
    questions  integer NOT NULL DEFAULT 0,
    tokens_in  bigint  NOT NULL DEFAULT 0,
    tokens_out bigint  NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

-- ---------------------------------------------------------------------------
-- Ingestion health
-- ---------------------------------------------------------------------------

CREATE TABLE job_runs (
    id          bigserial   PRIMARY KEY,
    name        text        NOT NULL,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status      text        NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows        integer,
    error       text
);
CREATE INDEX job_runs_name_idx ON job_runs (name, started_at DESC);

-- ---------------------------------------------------------------------------
-- Base views (splits are built on these; add more in new migrations)
-- ---------------------------------------------------------------------------

-- Player rows with match context: venue, opponent, kickoff. Finished matches only.
CREATE VIEW player_match_rows AS
SELECT pms.*,
       f.season,
       f.matchweek,
       f.kickoff_at,
       CASE WHEN pms.team_id = f.home_id THEN 'home' ELSE 'away' END      AS venue,
       CASE WHEN pms.team_id = f.home_id THEN f.away_id ELSE f.home_id END AS opponent_id
FROM player_match_stats pms
JOIN fixtures f ON f.id = pms.fixture_id
WHERE f.status = 'finished';

-- Team rows with match context and result. Finished matches only.
CREATE VIEW team_match_rows AS
SELECT tms.*,
       f.season,
       f.matchweek,
       f.kickoff_at,
       CASE WHEN tms.venue = 'home' THEN f.away_id ELSE f.home_id END AS opponent_id,
       CASE WHEN tms.goals_for > tms.goals_against THEN 'W'
            WHEN tms.goals_for = tms.goals_against THEN 'D'
            ELSE 'L' END                                              AS result
FROM team_match_stats tms
JOIN fixtures f ON f.id = tms.fixture_id
WHERE f.status = 'finished';

-- Latest price per bookmaker per selection.
CREATE VIEW odds_latest AS
SELECT DISTINCT ON (fixture_id, market, line, selection, bookmaker) *
FROM odds_snapshots
ORDER BY fixture_id, market, line, selection, bookmaker, captured_at DESC;
