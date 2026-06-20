-- Add a free-form GeoJSON geometry column to Location for area-shaped
-- places (provinces, commanderies, large counties). Stored as JSONB
-- so future PostGIS / topology queries are possible without rewriting
-- the column, and so a malformed entry blows up at insert time rather
-- than at render time.
--
-- Render-time precedence (set in app/blueprints/main/views.py /map):
--   1. latitude + longitude → plot as a single pin
--   2. geojson present       → plot as a polygon overlay
--   3. neither              → location is omitted from the map
--
-- Idempotent.

ALTER TABLE location
    ADD COLUMN IF NOT EXISTS geojson JSONB;
