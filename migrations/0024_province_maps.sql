-- Province maps: one uploaded map image per Province-type Location,
-- plus hand-placed overlay geometry for the province's child locations.
--
-- province_map.location_id is UNIQUE — one map per province; replacing
-- the image reuses the row. Placement geometry lives in IMAGE-PIXEL
-- coordinates (JSONB): kind 'point' stores [x, y]; 'line' and 'region'
-- store [[x, y], ...]. `kind` is copied from the location type's
-- point_type at save time so old placements stay renderable even if
-- the type's placement style is changed later.
--
-- location_type.point_type drives the editor's placement mode:
-- 'point' (single coordinate), 'line' (freehand stroke — rivers,
-- walls), 'region' (clicked-out polygon).
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS province_map (
    id          SERIAL PRIMARY KEY,
    location_id INTEGER NOT NULL UNIQUE REFERENCES location(id) ON DELETE CASCADE,
    filename    VARCHAR(255) NOT NULL,
    source_site VARCHAR(255) NOT NULL DEFAULT '',
    source_url  VARCHAR(2048) NOT NULL DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    created_by  VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    last_edited_by VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS province_map_placement (
    id              SERIAL PRIMARY KEY,
    province_map_id INTEGER NOT NULL REFERENCES province_map(id) ON DELETE CASCADE,
    location_id     INTEGER NOT NULL REFERENCES location(id) ON DELETE CASCADE,
    kind            VARCHAR(10) NOT NULL DEFAULT 'point',
    geometry        JSONB NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    created_by      VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    last_edited_by  VARCHAR(64),
    UNIQUE (province_map_id, location_id)
);

CREATE INDEX IF NOT EXISTS ix_province_map_placement_map_id
    ON province_map_placement (province_map_id);

ALTER TABLE location_type
    ADD COLUMN IF NOT EXISTS point_type VARCHAR(10) NOT NULL DEFAULT 'point';
