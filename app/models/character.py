from app import db
from app.models.abstract import AbstractObject, AbstractTag
from sqlalchemy.ext.hybrid import hybrid_property

# All locally-downloaded portrait files live under app/static/PORTRAIT_DIR/.
# Compose with url_for('static', filename=Portrait.static_path) at render time.
PORTRAIT_DIR = "portraits"


class Character(AbstractObject):
    is_fictional = db.Column(db.Boolean, default=False)

    courtesty_name = db.Column(db.String(255), default="")
    chinese_courtesty_name = db.Column(db.String(255), default="")

    # Free-form date strings — wide enough to hold ranges and qualifiers
    # like "256 BC - 247 BC" or "June 195 BC". A real date type / range
    # is on the wishlist (ISSUES.md #20); 64 chars is the pragmatic stop
    # in the meantime.
    birth_date = db.Column(db.String(64), default="")
    death_date = db.Column(db.String(64), default="")

    ancestral_home = db.Column(db.String(255), default="")

    # Pre-computed total mentions of this character across the entire book.
    # Populated by `flask recount-book-mentions`; not live (scanning all
    # 120 chapters per page load would be too slow).
    book_mention_count = db.Column(db.Integer, default=0, nullable=False)

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

    # Primary faction = the faction the character is most associated with.
    # Often the chronologically latest, but not always (the role-defining
    # / public-perception one wins over strictly-latest). Drives the pill
    # highlight in chapter prose, the Faction column in listings, etc.
    primary_faction_id = db.Column(db.Integer, db.ForeignKey("faction.id"), default=None, nullable=True)
    primary_faction = db.relationship("Faction", foreign_keys=[primary_faction_id])

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

    # External links attached to this character. Polymorphic — Url has
    # target_type/target_id directly; no FK on target_id since the same
    # column points across tables. `viewonly` because writes happen
    # through the Url row itself (admin add/remove routes), not through
    # appending to character.urls.
    urls = db.relationship(
        'Url',
        primaryjoin=(
            "and_(Character.id == foreign(Url.target_id), "
            "Url.target_type == 'character')"
        ),
        viewonly=True,
        order_by='Url.name',
    )

    # Define a composite unique constraint on the combination of fields
    __table_args__ = (
        db.UniqueConstraint('name', 'birth_date', 'death_date', 'ancestral_home', name='uix_character_composite_id'),
    )

    def __repr__(self):
        return f'<Character {self.name}>'

    def set_primary_faction(self, faction):
        # Keep `primary_faction` (FK) and the `factions` M2M consistent.
        # Caller should add `faction` to `factions` themselves if the
        # instance isn't yet persisted (the dynamic relationship can't
        # be queried for transient rows).
        if faction is None:
            self.primary_faction = None
            return
        self.primary_faction = faction
        try:
            if faction not in self.factions.all():
                self.factions.append(faction)
        except Exception:
            # Transient instance or detached session — caller maintains M2M.
            pass

    def get_all_name_labels(self):
        """Return every label this character matches by in chapter prose:
        the canonical name, the courtesy name (if set), and every alias
        from the comma-delimited `aliases` field.

        Each label is .strip()'d so we never emit a needle with a
        leading / trailing whitespace character. Older `aliases` values
        stored before _normalize_csv() landed (or scraped from
        Wikipedia where ", " is the usual delimiter) can carry such
        whitespace; without this strip the inline pill ends up
        rendering ` Lord Cao` with a literal leading space."""
        labels = []
        if self.name:
            n = self.name.strip()
            if n:
                labels.append(n)
        if self.courtesty_name:
            c = self.courtesty_name.strip()
            if c:
                labels.append(c)
        for alias in (self.aliases or '').split(','):
            alias = alias.strip()
            if alias:
                labels.append(alias)
        return labels

class Link(AbstractObject):
    character_id = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)

    character = db.relationship('Character', back_populates='links', lazy='select')

    def __repr__(self):
        return f'<Link {self.name}>'

class Role(AbstractTag):
    characters = db.relationship('Character', secondary=Character.role_table, back_populates='roles')
    urls = db.relationship(
        'Url',
        primaryjoin=(
            "and_(Role.id == foreign(Url.target_id), "
            "Url.target_type == 'role')"
        ),
        viewonly=True,
        order_by='Url.name',
    )
    def __repr__(self):
        return f'<Role {self.name}>'

class Faction(AbstractTag):
    characters = db.relationship('Character', secondary=Character.faction_table, back_populates='factions')
    urls = db.relationship(
        'Url',
        primaryjoin=(
            "and_(Faction.id == foreign(Url.target_id), "
            "Url.target_type == 'faction')"
        ),
        viewonly=True,
        order_by='Url.name',
    )
    def __repr__(self):
        return f'<Faction {self.name}>'

class Portrait(AbstractObject):
    character_id = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)

    # Original URL of the image on the source CDN. Kept for re-fetch / provenance;
    # the served image is always the local copy at static/PORTRAIT_DIR/<filename>.
    image_url = db.Column(db.Text, default="", nullable=False)

    # Basename of the locally-downloaded file, e.g. "42_koei.jpg".
    # The directory (PORTRAIT_DIR) is implicit so files can be relocated by
    # changing one constant. Use Portrait.static_path with url_for('static').
    filename = db.Column(db.String(255), default="", nullable=False)

    description = db.Column(db.Text, default="", nullable=False)

    # Where we found it, for crediting.
    source_url = db.Column(db.Text, default="", nullable=False)
    source_site = db.Column(db.String(255), default="", nullable=False)

    # Admin can hide a Portrait from public views (chapter sidebar, character
    # edit page) without deleting the row. New portraits start hidden — an
    # admin has to opt-in to public visibility, either by toggling Hide off
    # or by setting the portrait as the character's default (which auto-
    # unhides it as a side effect).
    is_hidden = db.Column(db.Boolean, default=True, nullable=False)

    # Exactly one Portrait per character can be the "default" — shown first
    # in the chapter sidebar. Enforced application-side by the set-default
    # admin route AND db-side by the partial unique index in __table_args__.
    is_default = db.Column(db.Boolean, default=False, nullable=False)

    character = db.relationship('Character', back_populates='portraits', lazy='select')

    # Polymorphic tag relationship — TagAssociation.target_type='portrait'.
    # viewonly=True because writes happen via TagAssociation rows directly
    # (see admin add/remove tag routes); the secondary-table mapper can't
    # safely write through a discriminator-filtered relationship.
    tags = db.relationship(
        'Tag',
        secondary='tag_association',
        primaryjoin=(
            "and_(Portrait.id == TagAssociation.target_id, "
            "TagAssociation.target_type == 'portrait')"
        ),
        secondaryjoin='Tag.id == TagAssociation.tag_id',
        viewonly=True,
        order_by='Tag.name',
    )

    __table_args__ = (
        # Allow many is_default=false rows per character; allow at most one
        # is_default=true. The corresponding raw DDL lives in
        # migrations/0001_partial_unique_default_portrait.sql for existing
        # DBs; this declaration makes flask create-all on a fresh DB include it.
        db.Index(
            'uniq_default_portrait_per_character',
            'character_id',
            unique=True,
            postgresql_where=db.text('is_default = true'),
        ),
    )

    @hybrid_property
    def static_path(self):
        """Path suitable for `url_for('static', filename=...)`. Empty if no file."""
        return f"{PORTRAIT_DIR}/{self.filename}" if self.filename else ""

    def __repr__(self):
        return f'<Portrait {self.name} from {self.source_site}>'