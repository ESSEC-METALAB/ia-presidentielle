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
    trust_level  INTEGER NOT NULL CHECK (trust_level BETWEEN 1 AND 4),
    archive_url  TEXT                -- Wayback capture /web/<14 digits>/..., or NULL
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
    out_of_window INTEGER NOT NULL DEFAULT 0,  -- returned but published before the window
    error       TEXT,
    PRIMARY KEY (run_id, source_id)
);

-- Segmentation. Rebuilt whenever the segmenter version changes; the documents
-- themselves are never modified.
CREATE TABLE IF NOT EXISTS segmentations (
    document_hash     TEXT PRIMARY KEY REFERENCES documents (content_hash),
    segmenter_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS segments (
    document_hash TEXT NOT NULL REFERENCES documents (content_hash),
    idx           INTEGER NOT NULL,
    text          TEXT NOT NULL,
    spans         TEXT NOT NULL,     -- JSON [[start, end], ...] in the document's text
    mentions      TEXT NOT NULL,     -- JSON [{"candidate_id": ..., "count": ...}, ...]
    PRIMARY KEY (document_hash, idx)
);

CREATE TABLE IF NOT EXISTS excluded_passages (
    document_hash TEXT NOT NULL REFERENCES documents (content_hash),
    start_char    INTEGER NOT NULL,
    end_char      INTEGER NOT NULL,
    reason        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS excluded_by_document ON excluded_passages (document_hash);

-- Annotation: one row per (passage, annotator version), the whole answer as JSON
-- (accepted statements and rejected proposals alike). A passage whose text changed is
-- annotated again: segment_hash is the hash of the text that was annotated.
CREATE TABLE IF NOT EXISTS segment_annotations (
    segment_id        TEXT NOT NULL,
    annotator_version TEXT NOT NULL,
    segment_hash      TEXT NOT NULL,
    annotated_at      TEXT NOT NULL,
    statements        INTEGER NOT NULL,  -- accepted, for reading the table by eye
    payload           TEXT NOT NULL,     -- SegmentAnnotation as JSON
    PRIMARY KEY (segment_id, annotator_version)
);

-- Tokens in and out of every LLM call, per step (CLAUDE.md §4, "Logs").
CREATE TABLE IF NOT EXISTS llm_usage (
    step          TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    recorded_at   TEXT NOT NULL
);

-- Framing: whether a statement presents AI as an opportunity, a threat, both or neither.
-- One row per (statement, framer version); key = passage id and a hash of the quote.
CREATE TABLE IF NOT EXISTS statement_framings (
    key            TEXT NOT NULL,
    framer_version TEXT NOT NULL,
    framed_at      TEXT NOT NULL,
    framing        TEXT NOT NULL,
    payload        TEXT NOT NULL,     -- StatementFraming as JSON
    PRIMARY KEY (key, framer_version)
);

-- Scores of a statement on the scales of config/scoring.yaml, with the reason and the
-- words of the quote each one rests on. Key as for framings.
CREATE TABLE IF NOT EXISTS statement_scores (
    key            TEXT NOT NULL,
    scorer_version TEXT NOT NULL,
    scored_at      TEXT NOT NULL,
    payload        TEXT NOT NULL,     -- StatementScore as JSON
    PRIMARY KEY (key, scorer_version)
);
