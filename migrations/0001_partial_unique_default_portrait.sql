-- Enforce exactly-one default portrait per character at the DB level.
--
-- The application layer (app/blueprints/admin/views.py:set_default_portrait)
-- clears the previous default before setting a new one, but this partial
-- unique index is the safety net against direct SQL touches, future
-- scrapers, or races. It allows any number of is_default=false rows per
-- character_id, but at most one is_default=true.
--
-- Safe to re-apply: CREATE INDEX IF NOT EXISTS is a no-op once the index
-- exists.

CREATE UNIQUE INDEX IF NOT EXISTS uniq_default_portrait_per_character
  ON portrait (character_id)
  WHERE is_default = true;
