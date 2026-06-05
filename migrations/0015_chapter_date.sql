-- Add a free-form date string to chapters.
--
-- Same shape as event.date / character.birth_date — VARCHAR(64) so it
-- accepts a single year ("190 AD"), a month + year ("February 168"),
-- or a range ("190-200"). Display string only; structured parsing
-- comes later (planned timeline view).
--
-- Idempotent.

ALTER TABLE chapter
    ADD COLUMN IF NOT EXISTS date VARCHAR(64) NOT NULL DEFAULT '';
