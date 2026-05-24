-- EventType: tag-style category for Events.
--
-- Mirrors url_type / faction / role schema (AbstractTag inheritance:
-- name + the three colour columns + Font Awesome icon string + soft-
-- delete + audit). Each Event optionally gets one event_type via a
-- nullable FK; deleting the type detaches but doesn't cascade.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS event_type (
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
    is_hidden BOOLEAN NOT NULL DEFAULT false
);

ALTER TABLE event
    ADD COLUMN IF NOT EXISTS event_type_id INTEGER REFERENCES event_type(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_event_event_type_id ON event (event_type_id);
