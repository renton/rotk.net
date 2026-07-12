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


class TestLocationTypePointType:
    def test_edit_saves_line(self, admin_client, db_session):
        client, _ = admin_client
        lt = LocationType(name='Pointable River')
        db_session.add(lt)
        db_session.commit()
        resp = client.post(f'/admin/location-types/{lt.id}/edit', data={
            'name': 'Pointable River', 'icon': '', 'point_type': 'line',
            'font_colour': '#ffffff', 'bg_colour': '#ffffff',
            'border_colour': '#ffffff',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        assert lt.point_type == 'line'

    def test_invalid_choice_rejected(self, admin_client, db_session):
        client, _ = admin_client
        lt = LocationType(name='Pointable Bad')
        db_session.add(lt)
        db_session.commit()
        client.post(f'/admin/location-types/{lt.id}/edit', data={
            'name': 'Pointable Bad', 'icon': '', 'point_type': 'blob',
            'font_colour': '#ffffff', 'bg_colour': '#ffffff',
            'border_colour': '#ffffff',
        }, follow_redirects=True)
        db_session.expire_all()
        assert lt.point_type == 'point'   # unchanged — choice invalid

    def test_form_renders_choices(self, admin_client, db_session):
        client, _ = admin_client
        lt = LocationType(name='Pointable Render')
        db_session.add(lt)
        db_session.commit()
        resp = client.get(f'/admin/location-types/{lt.id}/edit')
        assert b'Province-map placement type' in resp.data
        assert b'freehand stroke' in resp.data


import io
import os

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


@pytest.fixture(autouse=True)
def _clean_provincemap_files(app):
    """File writes don't roll back with the DB savepoint — clean up."""
    from app.models.province_map import PROVINCEMAP_DIR
    maps_dir = os.path.join(app.static_folder, PROVINCEMAP_DIR)
    os.makedirs(maps_dir, exist_ok=True)
    before = set(os.listdir(maps_dir))
    yield
    for name in set(os.listdir(maps_dir)) - before:
        os.remove(os.path.join(maps_dir, name))


def upload_map(client, prov, data_bytes=PNG, filename='map.png'):
    return client.post(
        f'/admin/province-maps/{prov.id}/upload',
        data={'source_site': '', 'source_url': '',
              'image_file': (io.BytesIO(data_bytes), filename)},
        content_type='multipart/form-data',
        follow_redirects=True,
    )


class TestListPage:
    def test_lists_only_provinces(self, admin_client, db_session):
        client, _ = admin_client
        prov, lt = make_province(db_session, name='Listed Province')
        factories.make_location(name='Not A Province')
        db_session.flush()
        resp = client.get('/admin/province-maps')
        assert resp.status_code == 200
        assert b'Listed Province' in resp.data
        assert b'Not A Province' not in resp.data

    def test_edit_locations_disabled_without_map(self, admin_client,
                                                 db_session):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Unmapped Province')
        db_session.flush()
        resp = client.get('/admin/province-maps')
        assert b'Upload a map image first' in resp.data
        assert f'/admin/province-maps/{prov.id}/editor'.encode() \
            not in resp.data

    def test_upload_enables_editor_and_counts(self, admin_client,
                                              db_session, app):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Mapped Province')
        child = factories.make_location(name='Mapped Child',
                                        parent_id=prov.id)
        db_session.commit()
        resp = upload_map(client, prov)
        assert b'uploaded' in resp.data
        m = ProvinceMap.query.filter_by(location_id=prov.id).one()
        assert m.filename == f'{prov.id}.png'
        assert os.path.exists(os.path.join(
            app.static_folder, 'provincemaps', m.filename))
        resp = client.get('/admin/province-maps')
        assert f'/admin/province-maps/{prov.id}/editor'.encode() in resp.data
        assert b'0 placed / 1 child location' in resp.data

    def test_upload_rejects_garbage(self, admin_client, db_session):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Garbage Province')
        db_session.commit()
        resp = upload_map(client, prov, b'<?php nope', 'map.png')
        assert b'look like a real image' in resp.data
        assert ProvinceMap.query.count() == 0

    def test_upload_rejects_non_province(self, admin_client, db_session):
        client, _ = admin_client
        loc = factories.make_location(name='Plain Loc')
        db_session.commit()
        resp = client.post(
            f'/admin/province-maps/{loc.id}/upload',
            data={'source_site': '', 'source_url': '',
                  'image_file': (io.BytesIO(PNG), 'map.png')},
            content_type='multipart/form-data')
        assert resp.status_code == 404

    def test_gating(self, client, user_client, db_session):
        assert client.get('/admin/province-maps').status_code == 302
        uclient, _ = user_client
        assert uclient.get('/admin/province-maps').status_code == 403


class TestEditor:
    def _setup(self, client, db_session):
        prov, _ = make_province(db_session, name='Editor Province')
        lt_river = LocationType(name='Editor River', point_type='line')
        lt_region = LocationType(name='Editor Region', point_type='region')
        db_session.add_all([lt_river, lt_region])
        db_session.flush()
        county = factories.make_location(name='Editor County',
                                         parent_id=prov.id)
        river = factories.make_location(name='Editor Waterway',
                                        parent_id=prov.id,
                                        location_type_id=lt_river.id)
        region = factories.make_location(name='Editor Zone',
                                         parent_id=prov.id,
                                         location_type_id=lt_region.id)
        db_session.commit()
        upload_map(client, prov)
        return prov, county, river, region

    def test_editor_404_without_map(self, admin_client, db_session):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='No Map Province')
        db_session.commit()
        assert client.get(
            f'/admin/province-maps/{prov.id}/editor').status_code == 404

    def test_editor_payload(self, admin_client, db_session):
        client, _ = admin_client
        prov, county, river, region = self._setup(client, db_session)
        resp = client.get(f'/admin/province-maps/{prov.id}/editor')
        assert resp.status_code == 200
        assert b'id="pme-payload"' in resp.data
        assert b'Editor County' in resp.data
        assert b'"point_type": "line"' in resp.data
        assert b'js/province_map_editor.js' in resp.data
        # Popup link template for the on-map click tooltips.
        assert b'location_edit_url_template' in resp.data

    def test_place_point_line_region(self, admin_client, db_session):
        client, _ = admin_client
        prov, county, river, region = self._setup(client, db_session)
        r = client.post(
            f'/admin/province-maps/{prov.id}/placements/{county.id}',
            json={'kind': 'point', 'geometry': [100.5, 200.25]})
        assert r.status_code == 200 and r.get_json()['created'] is True
        r = client.post(
            f'/admin/province-maps/{prov.id}/placements/{river.id}',
            json={'kind': 'line',
                  'geometry': [[1, 2], [3, 4], [5, 6]]})
        assert r.status_code == 200
        r = client.post(
            f'/admin/province-maps/{prov.id}/placements/{region.id}',
            json={'kind': 'region',
                  'geometry': [[0, 0], [10, 0], [10, 10]]})
        assert r.status_code == 200
        assert ProvinceMapPlacement.query.count() == 3

    def test_place_upserts(self, admin_client, db_session):
        client, _ = admin_client
        prov, county, *_ = self._setup(client, db_session)
        url = f'/admin/province-maps/{prov.id}/placements/{county.id}'
        client.post(url, json={'kind': 'point', 'geometry': [1, 1]})
        r = client.post(url, json={'kind': 'point', 'geometry': [9, 9]})
        assert r.get_json()['created'] is False
        pl = ProvinceMapPlacement.query.one()
        assert pl.geometry == [9, 9]

    def test_kind_must_match_type(self, admin_client, db_session):
        client, _ = admin_client
        prov, county, river, _ = self._setup(client, db_session)
        r = client.post(
            f'/admin/province-maps/{prov.id}/placements/{river.id}',
            json={'kind': 'point', 'geometry': [1, 1]})
        assert r.status_code == 400
        assert 'does not match' in r.get_json()['error']

    def test_geometry_shape_validated(self, admin_client, db_session):
        client, _ = admin_client
        prov, county, river, region = self._setup(client, db_session)
        bad = [
            (county, {'kind': 'point', 'geometry': [1]}),
            (county, {'kind': 'point', 'geometry': 'nope'}),
            (river, {'kind': 'line', 'geometry': [[1, 2]]}),
            (region, {'kind': 'region', 'geometry': [[1, 2], [3, 4]]}),
        ]
        for loc, body in bad:
            r = client.post(
                f'/admin/province-maps/{prov.id}/placements/{loc.id}',
                json=body)
            assert r.status_code == 400, (loc.name, body)

    def test_foreign_child_rejected(self, admin_client, db_session):
        client, _ = admin_client
        prov, *_ = self._setup(client, db_session)
        outsider = factories.make_location(name='Outsider Loc')
        db_session.commit()
        r = client.post(
            f'/admin/province-maps/{prov.id}/placements/{outsider.id}',
            json={'kind': 'point', 'geometry': [1, 1]})
        assert r.status_code == 400

    def test_delete_placement(self, admin_client, db_session):
        client, _ = admin_client
        prov, county, *_ = self._setup(client, db_session)
        client.post(f'/admin/province-maps/{prov.id}/placements/{county.id}',
                    json={'kind': 'point', 'geometry': [1, 1]})
        r = client.post(
            f'/admin/province-maps/{prov.id}/placements/{county.id}/delete',
            json={})
        assert r.status_code == 200
        assert ProvinceMapPlacement.query.count() == 0
        # Deleting again → 404.
        r = client.post(
            f'/admin/province-maps/{prov.id}/placements/{county.id}/delete',
            json={})
        assert r.status_code == 404
