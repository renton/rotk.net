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
from app.models.abstract import AbstractObject, AbstractTag
from app.models.chapter import Chapter


# Conventional parent-type chain for the hierarchical types. Looked up
# by name (the AbstractTag UNIQUE field), not id, so seed-order doesn't
# matter. Used by the admin form to pre-filter the parent picker — the
# database itself stays permissive (parent_id is a free FK to any
# Location), so e.g. a PASS or BATTLEFIELD can attach to any ancestor
# the source actually mentions.
LOCATION_TYPE_PARENT_HIERARCHY = {
    'PROVINCE':   None,
    'COMMANDERY': 'PROVINCE',
    'COUNTY':     'COMMANDERY',
    'CITY':       'COUNTY',
}


def expected_parent_type_name(child_type_name):
    """Return the LocationType.name conventionally above `child_type_name`,
    or None for PROVINCE (top of the chain) and for non-hierarchical types
    (PASS, MOUNTAIN, etc. — they can parent to anything)."""
    return LOCATION_TYPE_PARENT_HIERARCHY.get(child_type_name)


class LocationType(AbstractTag):
    """A category for Locations (PROVINCE, COMMANDERY, COUNTY, CITY,
    PASS, MOUNTAIN, RIVER, BATTLEFIELD, ...). Inherits AbstractTag for
    the unique name, three colour columns, and Font Awesome icon string.

    The first four types form the conventional administrative hierarchy
    (see LOCATION_TYPE_PARENT_HIERARCHY); the rest are free-form."""
    locations = db.relationship('Location', back_populates='location_type')

    def __repr__(self):
        return f'<LocationType {self.name}>'


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

    # Tag-style classification. Nullable so existing rows survive the
    # migration; admins backfill from the edit page. ON DELETE SET NULL
    # — losing a LocationType detaches its locations rather than
    # cascading. Same pattern as event.event_type_id.
    location_type_id = db.Column(
        db.Integer,
        db.ForeignKey('location_type.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    location_type = db.relationship('LocationType', back_populates='locations')

    # Self-referential parent. Convention is one level up the
    # admin-division chain (CITY → COUNTY → COMMANDERY → PROVINCE), but
    # there's no structural constraint here — a PASS or BATTLEFIELD can
    # parent to any ancestor type the source happens to mention.
    parent_id = db.Column(
        db.Integer,
        db.ForeignKey('location.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    parent = db.relationship(
        'Location',
        remote_side='Location.id',
        back_populates='children',
    )
    children = db.relationship(
        'Location',
        back_populates='parent',
        order_by='Location.name',
    )

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
