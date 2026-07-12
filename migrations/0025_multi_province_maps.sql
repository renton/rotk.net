-- Multiple maps per province (e.g. "North part" / "South part").
--
-- Drops the one-map-per-province UNIQUE on province_map.location_id
-- and adds a display label. Placements were already keyed per-map
-- ((province_map_id, location_id) unique), so a child location can be
-- pinned independently on each of its province's maps — no placement
-- schema change needed.
--
-- Idempotent.

ALTER TABLE province_map
    ADD COLUMN IF NOT EXISTS label VARCHAR(120) NOT NULL DEFAULT '';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = 'province_map_location_id_key') THEN
        ALTER TABLE province_map
            DROP CONSTRAINT province_map_location_id_key;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_province_map_location_id
    ON province_map (location_id);
