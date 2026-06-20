-- Strip trailing "(town)" / "(city)" / "(pass)" / "(village)" / etc.
-- markers from Location.name.
--
-- The first cut of `flask import-admin-divisions` stored column-4 cells
-- like "Qiaomen 橋門 (town)" as name="Qiaomen (town)" with the
-- parenthetical preserved (and the type also inferred into
-- location_type_id). The type already classifies the row, so the
-- marker in the name was redundant — the import has been updated to
-- drop it. This migration backfills rows created before that change.
--
-- Pattern: a trailing parenthesised lowercase or uppercase word,
-- optionally preceded by whitespace. Trims any leftover whitespace
-- once the marker is gone.
--
-- Note: two rows that previously distinguished themselves only by
-- their marker (e.g. "Anyang (town)" vs "Anyang (city)") will both
-- collapse to "Anyang". They become true duplicates by name — clean
-- them up via the Merge UI on the Location edit page if you care.
-- location.name has no UNIQUE constraint so the UPDATE itself won't
-- fail.
--
-- Idempotent: re-running finds no matches once the cleanup has been
-- applied.

UPDATE location
SET name = TRIM(REGEXP_REPLACE(name, '\s*\([A-Za-z]+\)\s*$', ''))
WHERE name ~ '\s*\([A-Za-z]+\)\s*$';
