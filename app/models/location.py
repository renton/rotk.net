"""Location model — a place in the world (real or fictional) referenced
by the book. Lightweight on purpose: name (from AbstractObject),
optional latitude/longitude, and a notes field. Events point at a
Location via FK; an Event can also override the plotted point on a
per-event basis via `geo_point_override` (see app/models/event.py)."""
from app import db
from app.models.abstract import AbstractObject


class Location(AbstractObject):
    # `name` (from AbstractObject) is the display name. `aliases` /
    # `chinese_name` available too, though no UI for them yet.

    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

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
