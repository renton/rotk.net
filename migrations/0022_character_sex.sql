-- Character.sex: 'male' | 'female', defaulting male (the overwhelming
-- majority of the cast). Groundwork for deriving relationship labels
-- from the character rather than gendered RelationshipType pairs.
--
-- Idempotent.

ALTER TABLE character
    ADD COLUMN IF NOT EXISTS sex VARCHAR(10) NOT NULL DEFAULT 'male';
