from app import db
from app.models.abstract import AbstractObject, AbstractTag
from sqlalchemy.ext.hybrid import hybrid_property


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
        back_populates='characters',
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
        back_populates='characters',
        lazy='dynamic'
    )

    latest_faction_id = db.Column(db.Integer, db.ForeignKey("faction.id"), default=None, nullable=True)
    latest_faction = db.relationship("Faction", foreign_keys=[latest_faction_id])

    # Association table for many-to-many relationship
    chapter_character = db.Table('chapter_character',
        db.Column('chapter_id', db.Integer, db.ForeignKey('chapter.id'), primary_key=True),
        db.Column('character_id', db.Integer, db.ForeignKey('character.id'), primary_key=True)
    )

    chapters = db.relationship(
        'Chapter',
        secondary=chapter_character,
        back_populates='characters'
    )

    links = db.relationship('Link', back_populates='character', lazy='select')
    portraits = db.relationship('Portrait', back_populates='character', lazy='select')

    # Define a composite unique constraint on the combination of fields
    __table_args__ = (
        db.UniqueConstraint('name', 'birth_date', 'death_date', 'ancestral_home', name='uix_character_composite_id'),
    )

    def __repr__(self):
        return f'<Character {self.name}>'

    def set_current_faction(self, faction):
        # Keep `latest_faction` (FK) and the `factions` M2M consistent.
        # Caller should add `faction` to `factions` themselves if the
        # instance isn't yet persisted (the dynamic relationship can't
        # be queried for transient rows).
        if faction is None:
            self.latest_faction = None
            return
        self.latest_faction = faction
        try:
            if faction not in self.factions.all():
                self.factions.append(faction)
        except Exception:
            # Transient instance or detached session — caller maintains M2M.
            pass

    def get_all_name_labels(self):
        labels = [self.name]
        if self.courtesty_name != "":
            labels.append(self.courtesty_name)

        for alias in self.aliases.split(','):
            if alias != "":
                labels.append(alias)

        return labels

class Link(AbstractObject):
    character_id = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)

    character = db.relationship('Character', back_populates='links', lazy='select')

    def __repr__(self):
        return f'<Link {self.name}>'

class Role(AbstractTag):
    characters = db.relationship('Character', secondary=Character.role_table, back_populates='roles')
    def __repr__(self):
        return f'<Role {self.name}>'

class Faction(AbstractTag):
    characters = db.relationship('Character', secondary=Character.faction_table, back_populates='factions')
    def __repr__(self):
        return f'<Faction {self.name}>'

class Portrait(AbstractObject):
    character_id = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)

    # Direct URL of the image on the source CDN (e.g. Fandom's static.wikia.nocookie.net).
    image_url = db.Column(db.Text, default="", nullable=False)

    # Path under app/static/ where we cached the downloaded image, or NULL if
    # we're hot-linking to image_url. Stored as 'portraits/<file>' so it
    # composes with url_for('static', filename=portrait.local_path).
    local_path = db.Column(db.String(255), default=None, nullable=True)

    description = db.Column(db.Text, default="", nullable=False)

    # Where we found it, for crediting.
    source_url = db.Column(db.Text, default="", nullable=False)
    source_site = db.Column(db.String(255), default="", nullable=False)

    character = db.relationship('Character', back_populates='portraits', lazy='select')

    def __repr__(self):
        return f'<Portrait {self.name} from {self.source_site}>'