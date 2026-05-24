"""Event model — battles, treaties, court intrigues, etc. mentioned in the
book. Each Event optionally pins to a Location (FK), can override the
plotted geo-point per event (`geo_point_override`), and can be excluded
from a future map render (`hide_on_map`). Aliases (from AbstractObject)
hold the comma-delimited search terms used by the admin
event-associations tool to match the event in chapter prose."""
from app import db
from app.models.abstract import AbstractObject
from app.models.chapter import Chapter


event_chapter = db.Table(
    'event_chapter',
    db.Column('event_id',   db.Integer, db.ForeignKey('event.id'),   primary_key=True),
    db.Column('chapter_id', db.Integer, db.ForeignKey('chapter.id'), primary_key=True),
)


class Event(AbstractObject):
    # `name` + `aliases` (comma-delimited keywords) come from AbstractObject.

    location_id = db.Column(
        db.Integer,
        db.ForeignKey('location.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    location = db.relationship('Location', foreign_keys=[location_id])

    # Free-form override for the map plot point — used when the linked
    # Location's coords are wrong or the event happened somewhere distinct
    # from the canonical Location. Format intentionally open ("lat,lng" or
    # a place name, etc.) — interpreted by the future map renderer.
    geo_point_override = db.Column(db.String(255), default="")

    hide_on_map = db.Column(db.Boolean, default=False, nullable=False)

    chapters = db.relationship(
        'Chapter',
        secondary=event_chapter,
        back_populates='events',
    )

    urls = db.relationship(
        'Url',
        primaryjoin=(
            "and_(Event.id == foreign(Url.target_id), "
            "Url.target_type == 'event')"
        ),
        viewonly=True,
        order_by='Url.name',
    )

    def __repr__(self):
        return f'<Event {self.name}>'


# Wire the back-pop side onto Chapter without editing chapter.py — keeps
# the import order one-way (chapter.py shouldn't reach into event.py).
Chapter.events = db.relationship(
    'Event',
    secondary=event_chapter,
    back_populates='chapters',
)
