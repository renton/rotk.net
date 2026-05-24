-- Create the location, event, and event_chapter tables.
--
-- Location:    a place in the world (real or fictional). Lightweight.
--              name (collation 'C', case-sensitive bytewise — same rule
--              as Character), optional latitude/longitude, audit fields.
--
-- Event:       a thing that happened (battle, treaty, intrigue, ...).
--              FK to location (ON DELETE SET NULL — losing a location
--              shouldn't lose the event). geo_point_override is a
--              free-form string used by the future map renderer when
--              the linked Location is wrong/missing.
--              hide_on_map lets the admin suppress an event from any
--              future map render (Event is still searchable + visible
--              in listings).
--
-- event_chapter: plain M2M join. Matches the chapter_character pattern.
--              No audit fields here — see ISSUES.md if/when we want to
--              promote these to Association Objects.
--
-- Idempotent via IF NOT EXISTS on every DDL.

CREATE TABLE IF NOT EXISTS location (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) COLLATE "C" NOT NULL DEFAULT '',
    chinese_name VARCHAR(255) DEFAULT '',
    aliases VARCHAR(255) COLLATE "C" DEFAULT '',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    notes TEXT DEFAULT '',
    created_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS event (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) COLLATE "C" NOT NULL DEFAULT '',
    chinese_name VARCHAR(255) DEFAULT '',
    aliases VARCHAR(255) COLLATE "C" DEFAULT '',
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT false,
    notes TEXT DEFAULT '',
    created_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    location_id INTEGER REFERENCES location(id) ON DELETE SET NULL,
    geo_point_override VARCHAR(255) DEFAULT '',
    hide_on_map BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS ix_event_location_id ON event (location_id);

CREATE TABLE IF NOT EXISTS event_chapter (
    event_id   INTEGER NOT NULL REFERENCES event(id)   ON DELETE CASCADE,
    chapter_id INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, chapter_id)
);

CREATE INDEX IF NOT EXISTS ix_event_chapter_chapter_id ON event_chapter (chapter_id);
