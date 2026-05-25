"""External-link model.

UrlType: a category for Urls (e.g. "Wikipedia", "YouTube"). Inherits
AbstractTag so it gets a unique `name`, an `icon` string (used for a
Font Awesome class), the optional colour fields, and the audit stamps.

Url: a single external link attached to one first-class content object
(Character, Chapter, Faction, Tag, Role). Polymorphic owner via
target_type + target_id — same pattern as TagAssociation: no FK on
target_id because it points across tables. `name` (inherited from
AbstractObject) is the human-readable description shown next to the
link; `url` is the actual link; `favicon` is an optional path into
app/static/ for a small image to display alongside.
"""
from app import db
from app.models.abstract import AbstractObject, AbstractTag


class UrlType(AbstractTag):
    # `name` and `icon` come from AbstractTag.
    # `icon` holds a Font Awesome class string, e.g. "fa-brands fa-wikipedia-w".

    urls = db.relationship(
        'Url',
        back_populates='url_type',
        lazy='dynamic',
    )

    def __repr__(self):
        return f'<UrlType {self.name}>'


class Url(AbstractObject):
    # `name` (from AbstractObject) doubles as the human-readable description.
    url = db.Column(db.Text, default="", nullable=False)
    favicon = db.Column(db.String(255), default="")

    url_type_id = db.Column(
        db.Integer,
        db.ForeignKey('url_type.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    url_type = db.relationship('UrlType', back_populates='urls')

    # Polymorphic owner — see module docstring.
    target_type = db.Column(db.String(64), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.Index('ix_url_target', 'target_type', 'target_id'),
    )

    def __repr__(self):
        return f'<Url {self.name!r} -> {self.url}>'
