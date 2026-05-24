-- Per-snippet match exclusions.
--
-- Some inline-tag matches are wrong (e.g. a location alias that's
-- also part of a person's name). Rather than blanket-removing the
-- alias from the location (which would lose all the legitimate
-- matches), admins can mark individual snippets as "don't tag this
-- one" from the location-associations admin page.
--
-- Keyed by a fingerprint of the surrounding text — chapter id, the
-- target (polymorphic via target_type / target_id), the matched
-- substring, and the before/after context strings as rendered by
-- find_*_mentions(). At render time we load the set of fingerprints
-- for this chapter+target and skip any match whose fingerprint is in
-- the set.
--
-- target_type is polymorphic so the same table can later cover
-- event / character match exclusions; only 'location' is wired in
-- the UI for now.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS match_exclusion (
    id              SERIAL PRIMARY KEY,
    chapter_id      INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    target_type     VARCHAR(32) NOT NULL,
    target_id       INTEGER     NOT NULL,
    match_text      TEXT        NOT NULL,
    before_snippet  TEXT        NOT NULL DEFAULT '',
    after_snippet   TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
    created_by      VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system'
);

-- Lookup index: render-time queries scope to (chapter, target_type,
-- target_id) and pull the fingerprint set. Not unique — a duplicate
-- exclusion row is harmless, the set lookup dedupes by membership.
CREATE INDEX IF NOT EXISTS ix_match_exclusion_chapter_target
    ON match_exclusion (chapter_id, target_type, target_id);
