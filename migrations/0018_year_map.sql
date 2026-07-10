-- YearMap: one uploaded territory-map image per year (184–280 AD).
--
-- `year` is UNIQUE — a single canonical map per year; re-uploading
-- replaces the stored image. `filename` is the basename under
-- app/static/yearmaps/ (server-constructed, never user input).
-- `source_site` / `source_url` are the same credit pair Portrait uses.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS year_map (
    id          SERIAL PRIMARY KEY,
    year        INTEGER     NOT NULL UNIQUE,
    filename    VARCHAR(255) NOT NULL,
    source_site VARCHAR(255) NOT NULL DEFAULT '',
    source_url  VARCHAR(2048) NOT NULL DEFAULT '',
    created_at  TIMESTAMP   NOT NULL DEFAULT now(),
    created_by  VARCHAR(64) NOT NULL DEFAULT 'rotk.net_system',
    last_edited_by VARCHAR(64)
);
