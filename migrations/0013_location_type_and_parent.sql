-- LocationType + Location.parent_id: classify locations and let them
-- nest hierarchically.
--
-- The conventional Three-Kingdoms-era geographic chain is
--   PROVINCE → COMMANDERY → COUNTY → CITY
-- but plenty of book locations (passes, temples, battlefields, fictional
-- towns) don't fit cleanly into a county or county-equivalent. So:
--
--   * location_type is a tag-style classification with the four
--     hierarchical types seeded by name, plus a handful of common
--     non-hierarchical ones (PASS, MOUNTAIN, RIVER, BATTLEFIELD). Admins
--     can add more from the /admin/url-types-style UI later.
--   * parent_id is a free self-FK to any Location — no structural
--     constraint on type pairings. The expected pairing (a CITY's parent
--     is conventionally a COUNTY) lives in app/models/location.py
--     (LOCATION_TYPE_PARENT_HIERARCHY) and is used by form-side defaults,
--     not enforced in the DB. Lets the admin attach a pass directly to a
--     commandery when the source doesn't tell us a county.
--
-- Both columns on `location` are NULLable so the migration is safe to
-- apply on an existing populated table; admins backfill from the UI.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS location_type (
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

ALTER TABLE location
    ADD COLUMN IF NOT EXISTS location_type_id INTEGER REFERENCES location_type(id) ON DELETE SET NULL;
ALTER TABLE location
    ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES location(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_location_location_type_id ON location (location_type_id);
CREATE INDEX IF NOT EXISTS ix_location_parent_id        ON location (parent_id);

-- Seed data is intentionally NOT here. Run `flask seed-location-types`
-- after the migration applies — keeps the migration pure-schema and
-- lets the seed list evolve without filing a new migration each time.
