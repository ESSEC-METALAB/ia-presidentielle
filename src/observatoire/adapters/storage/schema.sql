-- Raw documents and per-source run outcomes. Every document carries source_url,
-- fetched_at and content_hash (CLAUDE.md §4, "Idempotence").

CREATE TABLE IF NOT EXISTS documents (
    content_hash TEXT PRIMARY KEY,   -- SHA-256 of the normalised text: the dedup key
    source_id    TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    url          TEXT NOT NULL,
    title        TEXT,
    text         TEXT NOT NULL,
    published_on TEXT,               -- ISO date; NULL when the source states none, never guessed
    fetched_at   TEXT NOT NULL,      -- ISO 8601 with offset
    trust_level  INTEGER NOT NULL CHECK (trust_level BETWEEN 1 AND 4)
);

CREATE INDEX IF NOT EXISTS documents_by_source ON documents (source_id);

CREATE TABLE IF NOT EXISTS source_runs (
    run_id      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    fetched     INTEGER NOT NULL,    -- what the source returned: the liveness signal
    new         INTEGER NOT NULL,
    duplicates  INTEGER NOT NULL,
    error       TEXT,
    PRIMARY KEY (run_id, source_id)
);
