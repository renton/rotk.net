-- Annotations attached to a chapter's paragraphs (sections).
--
-- `section_text` is the whitespace-normalised full text of the
-- paragraph the annotation applies to. Content-addressed rather than
-- position-indexed so annotations don't orphan when other paragraphs
-- get edited around them. At render time each <p>'s text is hashed
-- (SHA-256, first 16 hex) and looked up in the payload; the icon
-- injection compares against `section_text` directly.
--
-- `is_public`:
--   true  -> visible to everyone; black notepad icon in the prose.
--   false -> only visible to admins; red notepad + red exclamation.
--
-- ON DELETE CASCADE on chapter_id — if a chapter row is removed,
-- annotations vanish with it.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS annotation (
    id            SERIAL PRIMARY KEY,
    chapter_id    INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    section_text  TEXT        NOT NULL,
    body          TEXT        NOT NULL,
    is_public     BOOLEAN     NOT NULL DEFAULT false,
    created_at    TIMESTAMP   NOT NULL DEFAULT now(),
    created_by    VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system'
);

CREATE INDEX IF NOT EXISTS ix_annotation_chapter_id ON annotation (chapter_id);
CREATE INDEX IF NOT EXISTS ix_annotation_is_public  ON annotation (is_public);
