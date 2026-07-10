from app import db

# Directory under app/static/ where year-map images live.
YEARMAP_DIR = 'yearmaps'

# The Three Kingdoms era span covered by the Yearly Maps admin page:
# 184 (Yellow Turban Rebellion) through 280 (Jin unification).
YEARMAP_FIRST_YEAR = 184
YEARMAP_LAST_YEAR = 280


class YearMap(db.Model):
    """One territory-map image per year. `year` is unique — uploading
    for a year that already has a map replaces it.

    `source_site` / `source_url` are the same credit-pair shape Portrait
    uses: a display label for where the image came from, plus an optional
    originating URL."""
    __tablename__ = 'year_map'

    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False, unique=True)
    filename = db.Column(db.String(255), nullable=False)
    source_site = db.Column(db.String(255), nullable=False, default='')
    source_url = db.Column(db.String(2048), nullable=False, default='')
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    created_by = db.Column(db.String(64), nullable=False, default='rotk.net_system')
    last_edited_by = db.Column(db.String(64))

    # Factions present on this year's map — admin-curated from the
    # Yearly Maps modal. The set is REPLACED wholesale on every modal
    # save (the hidden faction_ids field carries the full list).
    faction_table = db.Table(
        'year_map_faction',
        db.Column('year_map_id', db.ForeignKey('year_map.id', ondelete='CASCADE'), primary_key=True),
        db.Column('faction_id', db.ForeignKey('faction.id', ondelete='CASCADE'), primary_key=True),
    )

    factions = db.relationship(
        'Faction',
        secondary=faction_table,
        order_by='Faction.name',
    )

    @property
    def static_path(self):
        return f'{YEARMAP_DIR}/{self.filename}'

    def __repr__(self):
        return f'<YearMap {self.year} {self.filename}>'
