-- Character / Location references on annotations.
--
-- At create time the server scans the annotation's section text
-- against the chapter's associated characters + locations (using the
-- same per-chapter keywords the prose renderer uses) and attaches
-- whatever it finds. Displayed in the annotation modal and as
-- filterable columns on the admin annotation list pages.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS annotation_character (
    annotation_id INTEGER NOT NULL REFERENCES annotation(id) ON DELETE CASCADE,
    character_id  INTEGER NOT NULL REFERENCES character(id)  ON DELETE CASCADE,
    PRIMARY KEY (annotation_id, character_id)
);

CREATE TABLE IF NOT EXISTS annotation_location (
    annotation_id INTEGER NOT NULL REFERENCES annotation(id) ON DELETE CASCADE,
    location_id   INTEGER NOT NULL REFERENCES location(id)   ON DELETE CASCADE,
    PRIMARY KEY (annotation_id, location_id)
);

CREATE INDEX IF NOT EXISTS ix_annotation_character_character_id
    ON annotation_character (character_id);
CREATE INDEX IF NOT EXISTS ix_annotation_location_location_id
    ON annotation_location (location_id);
