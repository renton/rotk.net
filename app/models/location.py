"""Location model — a place in the world (real or fictional) referenced
by the book. Lightweight on purpose: name (from AbstractObject),
optional latitude/longitude, and a notes field. Events point at a
Location via FK; an Event can also override the plotted point on a
per-event basis via `geo_point_override` (see app/models/event.py).

Locations can also be associated directly with chapters via the
chapter_location M2M, for places that get mentioned in a chapter
independent of any specific Event. The chapter sidebar de-dupes
event-pinned + directly-associated locations into one list."""
from app import db
from app.models.abstract import AbstractObject
from app.models.chapter import Chapter


chapter_location = db.Table(
    'chapter_location',
    db.Column('chapter_id',  db.Integer, db.ForeignKey('chapter.id'),  primary_key=True),
    db.Column('location_id', db.Integer, db.ForeignKey('location.id'), primary_key=True),
    # Per-(chapter, location) comma-delimited keyword list — replaces
    # the global `location.aliases` for chapter-prose matching.
    db.Column('keywords', db.Text, nullable=False, default=''),
)


class Location(AbstractObject):
    # `name` (from AbstractObject) is the display name. `aliases` /
    # `chinese_name` available too, though no UI for them yet.

    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    chapters = db.relationship(
        'Chapter',
        secondary=chapter_location,
        back_populates='locations',
    )

    # Polymorphic URL attachments — same pattern as Character / Faction.
    urls = db.relationship(
        'Url',
        primaryjoin=(
            "and_(Location.id == foreign(Url.target_id), "
            "Url.target_type == 'location')"
        ),
        viewonly=True,
        order_by='Url.name',
    )

    def __repr__(self):
        return f'<Location {self.name}>'


# Back-pop on Chapter, defined here so chapter.py doesn't have to reach
# into location.py — same trick the Event model uses for Chapter.events.
Chapter.locations = db.relationship(
    'Location',
    secondary=chapter_location,
    back_populates='chapters',
)
