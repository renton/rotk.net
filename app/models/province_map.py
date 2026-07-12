"""Per-province map images with hand-placed location overlays.

A ProvinceMap is one uploaded image for a Province-type Location
(`location_id` UNIQUE). ProvinceMapPlacement rows pin the province's
child locations onto that image with geometry in IMAGE-PIXEL
coordinates — the admin editor (/admin/province-maps/<id>/editor)
writes them, kind driven by the child's LocationType.point_type:

    point  → geometry [x, y]           (single coordinate, FA icon)
    line   → geometry [[x, y], ...]    (freehand stroke — rivers, walls)
    region → geometry [[x, y], ...]    (clicked-out polygon)

`kind` is copied onto the placement at save time so existing rows stay
renderable even if the type's point_type changes later.
"""
from sqlalchemy.dialects.postgresql import JSONB

from app import db

PROVINCEMAP_DIR = 'provincemaps'

POINT_TYPES = ('point', 'line', 'region')


class ProvinceMap(db.Model):
    __tablename__ = 'province_map'

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(
        db.Integer, db.ForeignKey('location.id', ondelete='CASCADE'),
        nullable=False, unique=True)
    filename = db.Column(db.String(255), nullable=False)
    source_site = db.Column(db.String(255), nullable=False, default='')
    source_url = db.Column(db.String(2048), nullable=False, default='')
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    created_by = db.Column(db.String(64), nullable=False, default='rotk.net_system')
    last_edited_by = db.Column(db.String(64))

    location = db.relationship('Location', foreign_keys=[location_id])
    placements = db.relationship(
        'ProvinceMapPlacement',
        back_populates='province_map',
        cascade='all, delete-orphan',
    )

    @property
    def static_path(self):
        return f'{PROVINCEMAP_DIR}/{self.filename}'

    def __repr__(self):
        return f'<ProvinceMap location={self.location_id} {self.filename}>'


class ProvinceMapPlacement(db.Model):
    __tablename__ = 'province_map_placement'

    id = db.Column(db.Integer, primary_key=True)
    province_map_id = db.Column(
        db.Integer, db.ForeignKey('province_map.id', ondelete='CASCADE'),
        nullable=False, index=True)
    location_id = db.Column(
        db.Integer, db.ForeignKey('location.id', ondelete='CASCADE'),
        nullable=False)
    kind = db.Column(db.String(10), nullable=False, default='point')
    geometry = db.Column(JSONB, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    created_by = db.Column(db.String(64), nullable=False, default='rotk.net_system')
    last_edited_by = db.Column(db.String(64))

    province_map = db.relationship('ProvinceMap', back_populates='placements')
    location = db.relationship('Location', foreign_keys=[location_id])

    __table_args__ = (
        db.UniqueConstraint('province_map_id', 'location_id',
                            name='uix_province_map_placement'),
    )

    def __repr__(self):
        return (f'<ProvinceMapPlacement map={self.province_map_id} '
                f'loc={self.location_id} {self.kind}>')
