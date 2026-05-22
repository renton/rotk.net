"""Audit log row.

One row per ORM insert / update / delete. The writers live in
app/edit_log.py — Mapper-level SQLAlchemy event listeners that fire
inside the same DB transaction as the change itself, so an audit row
either both lands or both rolls back with whatever it was logging.

`changes` is Postgres JSONB:
  - create: flat dict of {column: initial_value}
  - update: {column: {"old": ..., "new": ...}} for changed columns only,
            plus an optional "_relationships" sub-key for added/removed
            many-to-many or one-to-many items.
  - delete: flat dict of {column: final_value}
"""
from sqlalchemy.dialects.postgresql import JSONB

from app import db


class Edit(db.Model):
    __tablename__ = 'edit'

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    created_at = db.Column(db.DateTime, default=db.func.now(), nullable=False, index=True)
    target_type = db.Column(db.String(64), nullable=False, index=True)
    target_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(16), nullable=False, index=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey('user.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # Stored at edit-time so we keep the attribution even if the user is
    # later deleted (FK is ON DELETE SET NULL).
    user_label = db.Column(db.String(120), nullable=False, default='')

    changes = db.Column(JSONB, nullable=False, default=dict)

    user = db.relationship('User')

    def __repr__(self):
        return (
            f'<Edit {self.action} {self.target_type}/{self.target_id} '
            f'by {self.user_label!r}>'
        )
