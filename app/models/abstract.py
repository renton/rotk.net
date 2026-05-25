from sqlalchemy.sql import func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import mapped_column
from app import db

class AbstractObject(db.Model):
    __abstract__ = True

    # mapped_column + sorted_order ensure columns get added to furthest most left in table when inherited
    id = mapped_column(db.Integer, primary_key=True, sort_order=-1)
    # collation='C' = binary/byte-wise comparison (Postgres). Treats similar
    # characters as distinct (e.g. U, u, ü) — same intent as MySQL's
    # utf8mb4_bin in the previous incarnation.
    name = mapped_column(db.String(255, collation='C'), default="", nullable=False, sort_order=-1)
    chinese_name = mapped_column(db.String(255), default="", sort_order=-1)
    aliases = mapped_column(db.String(255, collation='C'), default="", sort_order=-1)
    created_at = mapped_column(db.DateTime, default=db.func.now(), sort_order=-1)
    #updated_at = mapped_column(db.DateTime, onupdate=db.func.now(), sort_order=-1)
    updated_at = mapped_column(db.DateTime, sort_order=-1)

    # Audit stamps. The ORM hooks in app/models/audit.py auto-populate these
    # on insert/update from `current_user` when there's a request context,
    # falling back to "rotk.net_system" for CLI / scraper activity. Plain
    # string (rather than FK to user.id) keeps history readable even after
    # a user is deleted.
    created_by = mapped_column(db.String(64), default="rotk.net_system",
                               nullable=False, sort_order=-1)
    last_edited_by = mapped_column(db.String(64), default="rotk.net_system",
                                   nullable=False, sort_order=-1)

    is_deleted = mapped_column(db.Boolean, default=False, nullable=False, sort_order=-1)
    
    notes = db.Column(db.Text, default="")

    @hybrid_property
    def cleaned_name(self):
        cleaned_name = ''.join(c for c in (self.name or "") if c not in '(){}<>/')
        return cleaned_name.replace(' ', '_').replace('-','_')

    @classmethod
    def get_all_active(cls):
        return cls.query.filter(cls.is_deleted == False).order_by(cls.name.asc()).all()

    def __repr__(self):
        return f'<AbstractObject {self.name}>'

class AbstractTag(AbstractObject):
    __abstract__ = True

    name = mapped_column(db.String(255, collation='C'), default="", nullable=False, sort_order=-1, unique=True)
    font_colour = db.Column(db.String(7), default="#ffffff")
    bg_colour = db.Column(db.String(7), default="#ffffff")
    border_colour = db.Column(db.String(7), default="#ffffff")
    icon = db.Column(db.String(80), default="")
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)

    @hybrid_property
    def default_colour(self):
        return "#ffffff"

    def __repr__(self):
        return f'<AbstractTag {self.name}>'