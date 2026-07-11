-- Sex-aware relationship labels.
--
-- The existing side1_label / side2_label become the MALE / default
-- labels; these new columns optionally override per end when the
-- character occupying that end is female. Blank female label = use the
-- default. Lets one "Parent/Child" type render as Father / Mother /
-- Son / Daughter based on each character's `sex`.
--
-- Idempotent.

ALTER TABLE relationship_type
    ADD COLUMN IF NOT EXISTS side1_label_female VARCHAR(64) NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS side2_label_female VARCHAR(64) NOT NULL DEFAULT '';
