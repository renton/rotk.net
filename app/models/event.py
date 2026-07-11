"""Event model — battles, treaties, court intrigues, etc. mentioned in the
book. Each Event optionally pins to a Location (FK), an EventType (FK
giving the event a coloured/iconed category), can override the plotted
geo-point per event (`geo_point_override`), and can be excluded from a
future map render (`hide_on_map`). Aliases (from AbstractObject) hold
the comma-delimited search terms used by the admin event-associations
tool to match the event in chapter prose."""
from app import db
from app.models.abstract import AbstractObject, AbstractTag
from app.models.chapter import Chapter


# Sided event ↔ faction participation. One table with a `side`
# discriminator (1 or 2) rather than two M2M tables — Event.factions1 /
# Event.factions2 are relationships filtered on it. `side` is part of
# the PK so a faction can (rarely) sit on both sides of the same event.
# Writes go through this table directly (see the add/remove routes in
# main/views) — the relationships below are viewonly so the side value
# is always explicit, never guessed by the ORM.
event_faction = db.Table(
    'event_faction',
    db.Column('event_id', db.Integer, db.ForeignKey('event.id', ondelete='CASCADE'), primary_key=True),
    db.Column('faction_id', db.Integer, db.ForeignKey('faction.id', ondelete='CASCADE'), primary_key=True),
    db.Column('side', db.SmallInteger, nullable=False, default=1, primary_key=True),
)


event_chapter = db.Table(
    'event_chapter',
    db.Column('event_id',   db.Integer, db.ForeignKey('event.id'),   primary_key=True),
    db.Column('chapter_id', db.Integer, db.ForeignKey('chapter.id'), primary_key=True),
    # Per-(event, chapter) comma-delimited keyword list. Same role as
    # `event.aliases` used to fill globally — the chapter renderer
    # consults this row instead.
    db.Column('keywords', db.Text, nullable=False, default=''),
)


class EventType(AbstractTag):
    """A category for Events (e.g. "Battle", "Court intrigue", "Treaty").
    Inherits AbstractTag so it gets a unique name + the three colour
    columns + a Font Awesome `icon` string used in the chapter sidebar
    badge."""
    events = db.relationship('Event', back_populates='event_type')

    # Display labels for the two faction lists on events of this type
    # ("Attackers"/"Defenders" for Battle, "Signatories"/"" for Treaty).
    # Empty factions1_label falls back to "Factions" at render time;
    # empty factions2_label means the second list doesn't apply to this
    # type (the edit page hides its picker; public views only render a
    # side that actually has factions).
    factions1_label = db.Column(db.String(64), nullable=False, default='')
    factions2_label = db.Column(db.String(64), nullable=False, default='')

    def __repr__(self):
        return f'<EventType {self.name}>'


class Event(AbstractObject):
    # `name` + `aliases` (comma-delimited keywords) come from AbstractObject.

    location_id = db.Column(
        db.Integer,
        db.ForeignKey('location.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    location = db.relationship('Location', foreign_keys=[location_id])

    event_type_id = db.Column(
        db.Integer,
        db.ForeignKey('event_type.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    event_type = db.relationship('EventType', back_populates='events')

    # Free-form date string (mirrors Character.birth_date / .death_date).
    # Accepts ranges, BC years, imprecise values — kept as text rather
    # than a typed DATE so historical sources with month/season-level
    # precision (or BC) don't have to be normalised.
    date = db.Column(db.String(64), default="", nullable=False)

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

    # The two sided faction lists (see event_faction above). Viewonly —
    # writes insert/delete event_faction rows directly so `side` is
    # always set explicitly.
    factions1 = db.relationship(
        'Faction',
        secondary=event_faction,
        primaryjoin='Event.id == event_faction.c.event_id',
        secondaryjoin='and_(Faction.id == event_faction.c.faction_id, event_faction.c.side == 1)',
        viewonly=True,
        order_by='Faction.name',
    )
    factions2 = db.relationship(
        'Faction',
        secondary=event_faction,
        primaryjoin='Event.id == event_faction.c.event_id',
        secondaryjoin='and_(Faction.id == event_faction.c.faction_id, event_faction.c.side == 2)',
        viewonly=True,
        order_by='Faction.name',
    )

    def factions_for_side(self, side):
        return self.factions1 if side == 1 else self.factions2

    def __repr__(self):
        return f'<Event {self.name}>'


# Wire the back-pop side onto Chapter without editing chapter.py — keeps
# the import order one-way (chapter.py shouldn't reach into event.py).
Chapter.events = db.relationship(
    'Event',
    secondary=event_chapter,
    back_populates='chapters',
)
