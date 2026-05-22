-- Audit log for admin / system actions across every model.
--
-- One row per insert / update / delete that goes through the ORM. The
-- writers are SQLAlchemy Mapper event listeners registered in
-- app/edit_log.py. The `changes` JSON column holds:
--   - on `create`: {col: new_value, ...}
--   - on `update`: {col: {old: ..., new: ...}, ...} (changed cols only)
--   - on `delete`: {col: final_value, ...}
-- Plus a `_relationships` sub-key when a tracked M2M / one-to-many
-- relationship was added/removed during the same flush.
--
-- Caveats (documented for the admin reading this in psql later):
-- - Bulk `Query.update()` / `Query.delete()` bypass ORM events and are
--   NOT logged. Use per-row writes in code that should be audited.
-- - The `user_id` FK is ON DELETE SET NULL so deleting a User doesn't
--   take their history with them; `user_label` preserves the name as
--   it was at edit time.

CREATE TABLE IF NOT EXISTS edit (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    target_type VARCHAR(64) NOT NULL,
    target_id   INTEGER,
    action      VARCHAR(16) NOT NULL,
    user_id     INTEGER REFERENCES "user"(id) ON DELETE SET NULL,
    user_label  VARCHAR(120) NOT NULL DEFAULT '',
    changes     JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_edit_created_at ON edit (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_edit_target     ON edit (target_type, target_id);
CREATE INDEX IF NOT EXISTS ix_edit_user_id    ON edit (user_id);
CREATE INDEX IF NOT EXISTS ix_edit_action     ON edit (action);
