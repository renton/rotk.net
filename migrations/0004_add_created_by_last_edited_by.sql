-- Add created_by / last_edited_by audit columns to every first-class
-- content table.
--
-- Existing rows are backfilled with the literal "rotk.net_system" — the
-- ALTER TABLE ... DEFAULT … NOT NULL form sets the default on existing
-- rows for us in Postgres 11+. New inserts going forward get auto-
-- stamped by the ORM hook in app/models/audit.py (admin username when
-- inside a Flask request, system fallback otherwise).
--
-- Plain string, not FK to user.id, so:
--   1. CLI / scraper inserts that have no user can stamp "rotk.net_system"
--      without an out-of-band user row existing.
--   2. Deleting a user later doesn't orphan their old contributions.
--
-- Tables covered:
--   character, chapter, faction, role, portrait, tag  (via AbstractObject)
--   tag_association                                    (audit fields added directly)
--
-- chapter_character is NOT covered — it's currently a plain join Table
-- with no Model class, and adding columns to it cleanly requires
-- promoting it to an Association Object (a sweep across the scanner /
-- admin views / chapter rendering). Deferred — covered by ISSUES if/when
-- we want it.

ALTER TABLE character        ADD COLUMN IF NOT EXISTS created_by     VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
ALTER TABLE character        ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';

ALTER TABLE chapter          ADD COLUMN IF NOT EXISTS created_by     VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
ALTER TABLE chapter          ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';

ALTER TABLE faction          ADD COLUMN IF NOT EXISTS created_by     VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
ALTER TABLE faction          ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';

ALTER TABLE role             ADD COLUMN IF NOT EXISTS created_by     VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
ALTER TABLE role             ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';

ALTER TABLE portrait         ADD COLUMN IF NOT EXISTS created_by     VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
ALTER TABLE portrait         ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';

ALTER TABLE tag              ADD COLUMN IF NOT EXISTS created_by     VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
ALTER TABLE tag              ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';

ALTER TABLE tag_association  ADD COLUMN IF NOT EXISTS created_by     VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
ALTER TABLE tag_association  ADD COLUMN IF NOT EXISTS last_edited_by VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system';
