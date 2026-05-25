-- Create the url_type and url tables.
--
-- UrlType is essentially a Faction/Role-flavoured tag: name + Font
-- Awesome icon class, plus the standard AbstractTag colour fields (we
-- don't render them yet, but the columns exist).
--
-- Url is a polymorphic child — one Url row attaches to exactly one
-- first-class object (Character / Chapter / Faction / Tag / Role) via
-- target_type + target_id. No FK on target_id since it points across
-- tables, matching the TagAssociation pattern. Lookups happen through
-- the composite index ix_url_target.
--
-- Both tables include the standard audit fields (created_at,
-- created_by, last_edited_by) — populated automatically by the
-- before_insert/before_update hooks in app/models/audit.py.
--
-- Idempotent on already-applied state via IF NOT EXISTS on the table
-- + index DDL.

CREATE TABLE IF NOT EXISTS url_type (
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

CREATE TABLE IF NOT EXISTS url (
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
    url TEXT NOT NULL DEFAULT '',
    favicon VARCHAR(255) DEFAULT '',
    url_type_id INTEGER REFERENCES url_type(id) ON DELETE SET NULL,
    target_type VARCHAR(64) NOT NULL,
    target_id INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_url_target ON url (target_type, target_id);
CREATE INDEX IF NOT EXISTS ix_url_url_type_id ON url (url_type_id);
