-- Event ↔ Faction participation, sided.
--
-- One association table with a `side` column (1 or 2) instead of two
-- M2M tables: Event.factions1 / Event.factions2 are relationships
-- filtered by side. A faction may appear on both sides of the same
-- event (side is part of the PK) — civil-war edge cases exist.
--
-- EventType gets a display label per side ("Attackers"/"Defenders" for
-- Battle, "Signatories"/"" for Treaty). Empty factions2_label means the
-- second list doesn't apply to that type: the edit page hides the
-- second picker and public views don't render an empty side.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS event_faction (
    event_id   INTEGER  NOT NULL REFERENCES event(id) ON DELETE CASCADE,
    faction_id INTEGER  NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
    side       SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (event_id, faction_id, side)
);

ALTER TABLE event_type ADD COLUMN IF NOT EXISTS factions1_label VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE event_type ADD COLUMN IF NOT EXISTS factions2_label VARCHAR(64) NOT NULL DEFAULT '';
