-- Soft-delete flag on annotations. Delete from the admin flips
-- is_deleted = true rather than removing the row; a checkbox on the
-- admin list pages toggles "show only deleted" for review / recovery.
--
-- Idempotent.

ALTER TABLE annotation
    ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS ix_annotation_is_deleted ON annotation (is_deleted);
