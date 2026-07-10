-- Faction leaders + YearMap factions.
--
-- faction_leader: M2M faction ↔ character — the character(s) leading a
-- faction. Set manually by admins on the faction edit page.
--
-- year_map_faction: M2M year_map ↔ faction — which factions are present
-- on a given year's territory map. Set from the Yearly Maps admin modal.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS faction_leader (
    faction_id   INTEGER NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    PRIMARY KEY (faction_id, character_id)
);

CREATE TABLE IF NOT EXISTS year_map_faction (
    year_map_id INTEGER NOT NULL REFERENCES year_map(id) ON DELETE CASCADE,
    faction_id  INTEGER NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
    PRIMARY KEY (year_map_id, faction_id)
);
