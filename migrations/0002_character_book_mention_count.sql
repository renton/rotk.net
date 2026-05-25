-- Add a precomputed book-wide mention count to Character. Populated by
-- `flask recount-book-mentions` (scans every chapter once and tallies per
-- character). Lets the chapter sidebar show "N mentions in this chapter"
-- and "M mentions in the book" without doing 120 regex passes per page
-- load.

ALTER TABLE character
  ADD COLUMN IF NOT EXISTS book_mention_count INTEGER NOT NULL DEFAULT 0;
