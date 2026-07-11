"""Family relationships between characters.

A RelationshipType names the two ends of a tie: side1_label / side2_label
("Father"/"Son", "Husband"/"Wife"). A blank side2_label makes the type
SYMMETRIC ("Brothers", "Cousins") — both ends display the side1 label.

A Relationship row stores one tie: character1 IS the side1 role (the
Father), character2 the side2 role (the Son). The tie is two-way by
construction — both characters' pages read the same row, each resolving
the OTHER end's label via `describe_for`. Adding "X is the son of Y"
therefore stores (character1=Y, character2=X).
"""
from app import db
from app.models.abstract import AbstractTag


class RelationshipType(AbstractTag):
    __tablename__ = 'relationship_type'

    side1_label = db.Column(db.String(64), nullable=False, default='')
    side2_label = db.Column(db.String(64), nullable=False, default='')

    @property
    def is_symmetric(self):
        return not self.side2_label

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

        The label names what the OTHER character is to the viewer:
        viewing from the side2 character (the Son), the other end shows
        side1_label ("Father"); viewing from side1 it shows side2_label
        — falling back to side1_label for symmetric types, then to the
        type name if no labels are set at all."""
        t = self.relationship_type
        if self.character1_id == character_id:
            other = self.character2
            label = t.side2_label or t.side1_label or t.name
        else:
            other = self.character1
            label = t.side1_label or t.name
        return other, label

    def __repr__(self):
        return (f'<Relationship {self.character1_id}-'
                f'{self.character2_id} type={self.relationship_type_id}>')
