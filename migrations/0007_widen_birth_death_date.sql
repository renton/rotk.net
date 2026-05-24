-- Widen character.birth_date and character.death_date from VARCHAR(4)
-- to VARCHAR(64). The original 4-char limit assumed plain 4-digit
-- years (e.g. "0220") but the source data carries BC years and ranges
-- ("256 BC - 247 BC", "June 195 BC") that overflow the limit and 500
-- the Add Character form.
--
-- VARCHAR(64) is the pragmatic stop — long enough for any realistic
-- date string in the source, short enough that the index/storage cost
-- is unchanged in practice. Real date typing / range columns are
-- still on the wishlist (ISSUES.md #20).
--
-- In Postgres, ALTER COLUMN TYPE VARCHAR(n) to a larger n is a
-- metadata-only operation — fast on a populated table, no row
-- rewriting. The DO-block guards make this idempotent: the ALTER
-- only fires when the column is still at the old size.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'character'
          AND column_name = 'birth_date'
          AND character_maximum_length = 4
    ) THEN
        ALTER TABLE character ALTER COLUMN birth_date TYPE VARCHAR(64);
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'character'
          AND column_name = 'death_date'
          AND character_maximum_length = 4
    ) THEN
        ALTER TABLE character ALTER COLUMN death_date TYPE VARCHAR(64);
    END IF;
END $$;
