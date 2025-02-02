from sqlalchemy.sql import func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import mapped_column
from app import db

class AbstractObject(db.Model):
    __abstract__ = True

    # mapped_column + sorted_order ensure columns get added to furthest most left in table when inherited
    id = mapped_column(db.Integer, primary_key=True, sort_order=-1)
    # collation='utf8mb4_bin' used so that similar characters are treated uniquely (ie. U, u, ü)
    name = mapped_column(db.String(255, collation='utf8mb4_bin'), default="", nullable=False, sort_order=-1)
    chinese_name = mapped_column(db.String(255), default="", sort_order=-1)
    aliases = mapped_column(db.String(255, collation='utf8mb4_bin'), default="", sort_order=-1)
    created_at = mapped_column(db.DateTime, default=db.func.now(), sort_order=-1)
    #updated_at = mapped_column(db.DateTime, onupdate=db.func.now(), sort_order=-1)   
    updated_at = mapped_column(db.DateTime, sort_order=-1)
    is_deleted = mapped_column(db.Boolean, default=False, nullable=False, sort_order=-1)
    
    notes = db.Column(db.Text, default="")

    @hybrid_property
    def cleaned_name(self):
        cleaned_name = ''.join(c for c in self.display_name if c not in '(){}<>/')
        return cleaned_name.replace(' ', '_').replace('-','_')

    @classmethod
    def get_all_active(cls):
        return cls.query.filter(cls.is_deleted == False).order_by(cls.name.asc()).all()

    def __repr__(self):
        return f'<AbstractObject {self.display_name}>'

class AbstractTag(AbstractObject):
    __abstract__ = True

    name = mapped_column(db.String(255, collation='utf8mb4_bin'), default="", nullable=False, sort_order=-1, unique=True)
    font_colour = db.Column(db.String(7), default="#ffffff")
    bg_colour = db.Column(db.String(7), default="#ffffff")
    border_colour = db.Column(db.String(7), default="#ffffff")
    icon = db.Column(db.String(80), default="")
    is_hidden = db.Column(db.Boolean, default=False, nullable=False)

    @hybrid_property
    def default_colour(self):
        return "#ffffff"

    def __repr__(self):
        return f'<AbstractTag {self.display_name}>'