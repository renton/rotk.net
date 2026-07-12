"""ProvinceMap system — model constraints, LocationType.point_type,
admin list/upload, and the placement editor endpoints."""
import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (Location, LocationType, ProvinceMap,
                        ProvinceMapPlacement)
from tests import factories


def make_province(db_session, name='Testzhou'):
    lt = LocationType.query.filter_by(name='Province').first()
    if lt is None:
        lt = LocationType(name='Province')
        db_session.add(lt)
        db_session.flush()
    return factories.make_location(name=name, location_type_id=lt.id), lt


class TestModels:
    def test_one_map_per_province(self, db_session):
        prov, _ = make_province(db_session)
        db_session.add(ProvinceMap(location_id=prov.id, filename='a.png'))
        db_session.flush()
        db_session.add(ProvinceMap(location_id=prov.id, filename='b.png'))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_one_placement_per_location_per_map(self, db_session):
        prov, _ = make_province(db_session)
        child = factories.make_location(name='Testxian', parent_id=prov.id)
        m = ProvinceMap(location_id=prov.id, filename='a.png')
        db_session.add(m)
        db_session.flush()
        db_session.add(ProvinceMapPlacement(
            province_map_id=m.id, location_id=child.id,
            kind='point', geometry=[10, 20]))
        db_session.flush()
        db_session.add(ProvinceMapPlacement(
            province_map_id=m.id, location_id=child.id,
            kind='point', geometry=[30, 40]))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_geometry_roundtrips_jsonb(self, db_session):
        prov, _ = make_province(db_session)
        child = factories.make_location(name='Riverine', parent_id=prov.id)
        m = ProvinceMap(location_id=prov.id, filename='a.png')
        db_session.add(m)
        db_session.flush()
        line = [[1.5, 2.25], [3.0, 4.75], [5.5, 6.0]]
        pl = ProvinceMapPlacement(province_map_id=m.id,
                                  location_id=child.id,
                                  kind='line', geometry=line)
        db_session.add(pl)
        db_session.flush()
        db_session.expire_all()
        assert pl.geometry == line

    def test_deleting_map_cascades_placements(self, db_session):
        prov, _ = make_province(db_session)
        child = factories.make_location(parent_id=prov.id)
        m = ProvinceMap(location_id=prov.id, filename='a.png')
        db_session.add(m)
        db_session.flush()
        db_session.add(ProvinceMapPlacement(
            province_map_id=m.id, location_id=child.id,
            kind='point', geometry=[1, 2]))
        db_session.flush()
        db_session.delete(m)
        db_session.flush()
        assert ProvinceMapPlacement.query.count() == 0

    def test_static_path(self, db_session):
        m = ProvinceMap(location_id=1, filename='42.png')
        assert m.static_path == 'provincemaps/42.png'

    def test_point_type_defaults_point(self, db_session):
        lt = LocationType(name='Pointy Default')
        db_session.add(lt)
        db_session.flush()
        assert lt.point_type == 'point'
