"""Family relationships between characters.

A RelationshipType names the two ends of a tie. Labels are SEX-AWARE:
side1_label / side2_label are the male / default labels, and
side1_label_female / side2_label_female optionally override them when
the character occupying that end is female — so one "Parent/Child" type
renders as Father / Mother / Son / Daughter depending on who's in the
row. Blank female label = use the default. A blank side-2 (both
columns) makes the type SYMMETRIC ("Siblings", "Cousins") — both ends
resolve through side 1's labels.

A Relationship row stores one tie: character1 IS the side1 role (the
Parent), character2 the side2 role (the Child). The tie is two-way by
construction — both characters' pages read the same row, each resolving
the OTHER end's label via `describe_for`. Adding "X is the child of Y"
therefore stores (character1=Y, character2=X).
"""
from app import db
from app.models.abstract import AbstractTag


class RelationshipType(AbstractTag):
    __tablename__ = 'relationship_type'

    # Male / default labels per end...
    side1_label = db.Column(db.String(64), nullable=False, default='')
    side2_label = db.Column(db.String(64), nullable=False, default='')
    # ...and optional female overrides (blank = use the default).
    side1_label_female = db.Column(db.String(64), nullable=False, default='')
    side2_label_female = db.Column(db.String(64), nullable=False, default='')

    @property
    def is_symmetric(self):
        return not (self.side2_label or self.side2_label_female)

    def end_label(self, side, sex=None):
        """The label for one end of the tie, resolved for the sex of the
        character occupying it. Falls back female → default; returns ''
        when that end has no labels at all (callers fall back to side 1
        / the type name)."""
        if side == 1:
            base, female = self.side1_label, self.side1_label_female
        else:
            base, female = self.side2_label, self.side2_label_female
        if sex == 'female' and female:
            return female
        return base

    def __repr__(self):
        return f'<RelationshipType {self.name}>'


class Relationship(db.Model):
    __tablename__ = 'relationship'

    id = db.Column(db.Integer, primary_key=True)
    character1_id = db.Column(
        db.Integer, db.ForeignKey('character.id', ondelete='CASCADE'),
        nullable=False, index=True)
    character2_id = db.Column(
        db.Integer, db.ForeignKey('character.id', ondelete='CASCADE'),
        nullable=False, index=True)
    relationship_type_id = db.Column(
        db.Integer, db.ForeignKey('relationship_type.id', ondelete='CASCADE'),
        nullable=False)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    created_by = db.Column(db.String(64), nullable=False, default='rotk.net_system')
    last_edited_by = db.Column(db.String(64))

    character1 = db.relationship('Character', foreign_keys=[character1_id])
    character2 = db.relationship('Character', foreign_keys=[character2_id])
    relationship_type = db.relationship('RelationshipType')

    __table_args__ = (
        db.UniqueConstraint('character1_id', 'character2_id',
                            'relationship_type_id',
                            name='uix_relationship_pair_type'),
    )

    def describe_for(self, character_id):
        """(other_character, label) as seen from `character_id`'s side.

        The label names what the OTHER character is to the viewer,
        resolved for the OTHER character's sex: viewing from the child's
        side of a Parent/Child tie, a female character1 shows "Mother".
        Falls back side2 → side1 (symmetric types), then to the type
        name when no labels are set at all."""
        t = self.relationship_type
        if self.character1_id == character_id:
            other = self.character2
            label = (t.end_label(2, other.sex)
                     or t.end_label(1, other.sex) or t.name)
        else:
            other = self.character1
            label = t.end_label(1, other.sex) or t.name
        return other, label

    def __repr__(self):
        return (f'<Relationship {self.character1_id}-'
                f'{self.character2_id} type={self.relationship_type_id}>')
