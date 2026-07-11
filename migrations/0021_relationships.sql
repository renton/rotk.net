-- Character relationships (family ties).
--
-- relationship_type: tag-shaped (mirrors event_type schema) plus one
-- label per end. side1_label/side2_label name the two ends of the tie
-- ("Father"/"Son", "Husband"/"Wife"); a blank side2_label means the
-- type is SYMMETRIC ("Brothers", "Cousins") — both ends display the
-- side1 label.
--
-- relationship: one row per tie. character1 IS the side1 role (the
-- Father in Father/Son), character2 the side2 role. Both ends read the
-- same row — adding "X is the son of Y" stores (Y, X, type). Deleting
-- either character cascades the row away.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS relationship_type (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) COLLATE "C" UNIQUE NOT NULL,
    chinese_name VARCHAR(255) DEFAULT '',
    aliases VARCHAR(255) COLLATE "C" DEFAULT '',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    notes TEXT DEFAULT '',
    created_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    font_colour VARCHAR(7) DEFAULT '#ffffff',
    bg_colour VARCHAR(7) DEFAULT '#ffffff',
    border_colour VARCHAR(7) DEFAULT '#ffffff',
    icon VARCHAR(80) DEFAULT '',
    is_hidden BOOLEAN NOT NULL DEFAULT false,
    side1_label VARCHAR(64) NOT NULL DEFAULT '',
    side2_label VARCHAR(64) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS relationship (
    id SERIAL PRIMARY KEY,
    character1_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    character2_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    relationship_type_id INTEGER NOT NULL REFERENCES relationship_type(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    last_edited_by VARCHAR(64),
    UNIQUE (character1_id, character2_id, relationship_type_id)
);

CREATE INDEX IF NOT EXISTS ix_relationship_character1_id ON relationship (character1_id);
CREATE INDEX IF NOT EXISTS ix_relationship_character2_id ON relationship (character2_id);
