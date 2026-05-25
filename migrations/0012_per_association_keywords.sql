-- Per-(chapter, target) keyword storage for the three association
-- editors. Each chapter_character / event_chapter / chapter_location
-- row gets its own comma-delimited keyword list; the chapter renderer
-- and the admin "live snippets" panel both read from these instead of
-- the global Character.aliases / Event.aliases / Location.aliases when
-- they're set, so "resync" on a chapter-association page now means
-- "replace keywords for THIS chapter only" — the global aliases on the
-- entity row stay untouched.
--
-- This migration adds the columns only — they start empty on every
-- existing row. Run `flask backfill-association-keywords` afterwards
-- to seed them from each target's current `name` + `aliases`. Until
-- that's done the chapter render falls back to the global aliases, so
-- nothing visibly breaks between migration and backfill.
--
-- Idempotent.

ALTER TABLE chapter_character
    ADD COLUMN IF NOT EXISTS keywords TEXT NOT NULL DEFAULT '';

ALTER TABLE event_chapter
    ADD COLUMN IF NOT EXISTS keywords TEXT NOT NULL DEFAULT '';

ALTER TABLE chapter_location
    ADD COLUMN IF NOT EXISTS keywords TEXT NOT NULL DEFAULT '';
