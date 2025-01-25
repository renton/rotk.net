from app import db
from app.models.abstract import AbstractObject, AbstractTag

class Character(AbstractObject):
    is_fictional = db.Column(db.Boolean, default=False)

    courtesty_name = db.Column(db.String(255), default="")
    chinese_courtesty_name = db.Column(db.String(255), default="")

    birth_date = db.Column(db.String(4), default="")
    death_date = db.Column(db.String(4), default="")

    ancestral_home = db.Column(db.String(255), default="")

    role_table = db.Table(
        'character_roles_association',
        db.Column('character_id', db.ForeignKey('character.id'), primary_key=True),
        db.Column('role_id', db.ForeignKey('role.id'), primary_key=True),
    )

    roles = db.relationship(
        'Role',
        secondary=role_table,
        backref=db.backref('character', lazy='dynamic'),
        lazy='dynamic'
    )

    faction_table = db.Table(
        'character_factions_association',
        db.Column('character_id', db.ForeignKey('character.id'), primary_key=True),
        db.Column('faction_id', db.ForeignKey('faction.id'), primary_key=True),
    )

    factions = db.relationship(
        'Faction',
        secondary=faction_table,
        backref=db.backref('character', lazy='dynamic'),
        lazy='dynamic'
    )

    #links = db.relationship('Link', backref='character', lazy=True)

    # Define a composite unique constraint on the combination of fields
    __table_args__ = (
        db.UniqueConstraint('name', 'birth_date', 'death_date', 'ancestral_home', name='uix_character_composite_id'),
    )

    # portraits

    # roles
    # factions

    # links = array of strings

    # @hybrid_property
    # def last_faction(self):
    #     return self.factions[-1]

    def __repr__(self):
        return f'<Character {self.name}>'

class Link(AbstractObject):
    character_id = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)

    def __repr__(self):
        return f'<Link {self.name}>'

class Role(AbstractTag):
    def __repr__(self):
        return f'<Role {self.name}>'

class Faction(AbstractTag):
    def __repr__(self):
        return f'<Faction {self.name}>'

#class Portrait
    # source
    # path