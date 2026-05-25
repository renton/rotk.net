-- Rename character.latest_faction_id -> character.primary_faction_id.
--
-- The field was originally meant to track the "latest" faction the
-- character belonged to (current/most-recent), but in practice it's
-- the faction readers most associate the character with, which isn't
-- always the chronologically latest one. Renaming makes the intent
-- match the field. Application-side renames in the same commit:
--
--   Character.latest_faction_id          -> primary_faction_id
--   Character.latest_faction (relation)  -> primary_faction
--   Character.set_current_faction()      -> set_primary_faction()
--   EditCharacterForm.latest_faction     -> primary_faction
--
-- Idempotent: wrapped in a DO block that only runs the rename if the
-- old column is still present. Safe to re-apply.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'character' AND column_name = 'latest_faction_id'
    ) THEN
        ALTER TABLE character RENAME COLUMN latest_faction_id TO primary_faction_id;
    END IF;
END $$;
