"""Free-form Tag + polymorphic TagAssociation.

A Tag is just a coloured label, like a Faction or Role but not tied to any
particular base object. Tags attach to anything via TagAssociation, which
stores (target_type, target_id) — e.g. ('character', 42) or ('chapter', 7).

We use a polymorphic association rather than per-pair join tables (the
Faction/Role pattern) because the taggable set is open-ended: characters,
chapters, locations, roles, portraits, future things. The trade-off is no
FK on target_id; uniqueness + a (target_type, target_id) index keep
queries fast and inserts deduplicated.
"""
from app import db
from app.models.abstract import AbstractTag


class Tag(AbstractTag):
    associations = db.relationship(
        'TagAssociation',
        back_populates='tag',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )

    @classmethod
    def get_or_create(cls, name):
        """Find a Tag by exact name, or create one with a name-seeded
        random palette. Returns (tag, was_created). Caller commits.

        Seeding the RNG by the tag name means the same variant
        (e.g. 'DW9') gets the same colours every time it's auto-created,
        regardless of which machine or run made it."""
        tag = cls.query.filter_by(name=name).first()
        if tag is not None:
            return tag, False

        import random
        from tools.colours import randomize_palette
        bg, font, border = randomize_palette(rng=random.Random(name))
        tag = cls(
            name=name,
            bg_colour=bg,
            font_colour=font,
            border_colour=border,
        )
        db.session.add(tag)
        return tag, True

    def __repr__(self):
        return f'<Tag {self.name}>'


class TagAssociation(db.Model):
    __tablename__ = 'tag_association'

    id = db.Column(db.Integer, primary_key=True)
    tag_id = db.Column(
        db.Integer,
        db.ForeignKey('tag.id', ondelete='CASCADE'),
        nullable=False,
    )

    # target_type matches the taggable's __tablename__ (e.g. 'character').
    # No FK is possible on target_id since it points across tables.
    target_type = db.Column(db.String(64), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, default=db.func.now())

    tag = db.relationship('Tag', back_populates='associations')

    __table_args__ = (
        db.UniqueConstraint('tag_id', 'target_type', 'target_id',
                            name='uix_tag_target'),
        db.Index('ix_tag_target', 'target_type', 'target_id'),
    )

    def __repr__(self):
        return f'<TagAssociation tag={self.tag_id} target={self.target_type}/{self.target_id}>'
