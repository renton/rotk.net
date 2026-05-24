-- Add a free-form date string to events.
--
-- Same shape as character.birth_date / character.death_date — VARCHAR(64)
-- so it accepts BC years, ranges ("208 AD - 209 AD"), or imprecise dates
-- ("Winter 208 AD"). Parsing / sortability comes later if needed; for
-- now it's a display string.
--
-- Idempotent.

ALTER TABLE event
    ADD COLUMN IF NOT EXISTS date VARCHAR(64) NOT NULL DEFAULT '';
