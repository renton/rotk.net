-- chapter_location M2M — direct chapter ↔ location association.
--
-- Parallel to chapter_character and event_chapter. Lets a chapter
-- reference locations that don't pin via an Event (e.g. a setting
-- description). The chapter sidebar de-dupes these against locations
-- already derived from the chapter's events.
--
-- Idempotent via IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS chapter_location (
    chapter_id  INTEGER NOT NULL REFERENCES chapter(id)  ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES location(id) ON DELETE CASCADE,
    PRIMARY KEY (chapter_id, location_id)
);

CREATE INDEX IF NOT EXISTS ix_chapter_location_location_id ON chapter_location (location_id);
