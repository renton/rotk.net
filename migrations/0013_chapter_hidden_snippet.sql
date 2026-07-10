-- Per-chapter hidden snippets. Admins highlight prose they want
-- suppressed from the public chapter view; each row stores a
-- content-addressed fingerprint (before / match_text / after) same
-- shape as match_exclusion. At render time the chapter view removes
-- these spans from `chapter.content` before any pill-tagging happens.
--
-- Not to be confused with match_exclusion: MatchExclusion suppresses
-- a specific occurrence of a NEEDLE from being wrapped as a
-- character/location pill (the prose text stays visible, just no
-- pill). ChapterHiddenSnippet removes the prose ENTIRELY. Different
-- concept, different table.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS chapter_hidden_snippet (
    id              SERIAL PRIMARY KEY,
    chapter_id      INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    match_text      TEXT        NOT NULL,
    before_snippet  TEXT        NOT NULL DEFAULT '',
    after_snippet   TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMP   NOT NULL DEFAULT now(),
    created_by      VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system'
);

CREATE INDEX IF NOT EXISTS ix_chapter_hidden_snippet_chapter_id
    ON chapter_hidden_snippet (chapter_id);
