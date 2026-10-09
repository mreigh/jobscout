-- 001: initial schema

-- Target companies (loaded from config/watchlist.csv in E1)
CREATE TABLE companies (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    segment         TEXT,
    tier            TEXT NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    status          TEXT,
    local_flag      TEXT,
    ats             TEXT,          -- greenhouse, lever, ashby, workday, ... or NULL until detected
    ats_token       TEXT,          -- board token / tenant identifier
    board_url       TEXT,          -- manual override always wins
    detected_at     TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every posting exactly as a source returned it, for replay (E2/E4)
CREATE TABLE raw_postings (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER REFERENCES runs(id),
    source          TEXT NOT NULL,  -- greenhouse, lever, gmail_linkedin, ...
    company_id      INTEGER REFERENCES companies(id),
    external_id     TEXT,
    url             TEXT,
    payload_json    TEXT NOT NULL,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_raw_source_ext ON raw_postings(source, external_id);

-- One canonical record per real job (E4)
CREATE TABLE jobs (
    id              INTEGER PRIMARY KEY,
    fingerprint     TEXT NOT NULL UNIQUE,
    company_id      INTEGER REFERENCES companies(id),
    title           TEXT NOT NULL,
    location        TEXT,
    remote          INTEGER,        -- 1 remote, 0 not, NULL unknown
    comp_min        INTEGER,
    comp_max        INTEGER,
    url             TEXT,
    description     TEXT,
    description_hash TEXT,
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT,
    filter_result   TEXT,           -- 'pass' or the rule that dropped it (E5)
    suppressed_reason TEXT          -- e.g. already in tracker (E7)
);
CREATE INDEX idx_jobs_company ON jobs(company_id);

-- Claude fit scores, cached per description version (E5)
CREATE TABLE scores (
    id              INTEGER PRIMARY KEY,
    job_id          INTEGER NOT NULL REFERENCES jobs(id),
    description_hash TEXT NOT NULL,
    score           INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    recommendation  TEXT NOT NULL,  -- apply, network_first, watch, skip
    result_json     TEXT NOT NULL,  -- rationale, gap flags, level read
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    scored_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (job_id, description_hash)
);

-- One row per CLI invocation that does work (JS-005)
CREATE TABLE runs (
    id              INTEGER PRIMARY KEY,
    command         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
    counts_json     TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    cost_usd        REAL NOT NULL DEFAULT 0
);
