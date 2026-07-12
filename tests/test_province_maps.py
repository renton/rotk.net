"""ProvinceMap system — model constraints, LocationType.point_type,
admin list/create/update/delete, and the placement editor endpoints.
Provinces may carry SEVERAL maps (labelled), each with independent
placements."""
import io
import os

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (Location, LocationType, ProvinceMap,
                        ProvinceMapPlacement)
from tests import factories

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def make_province(db_session, name='Testzhou'):
    lt = LocationType.query.filter_by(name='Province').first()
    if lt is None:
        lt = LocationType(name='Province')
        db_session.add(lt)
        db_session.flush()
    return factories.make_location(name=name, location_type_id=lt.id), lt


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


def create_map(client, prov, data_bytes=PNG, filename='map.png', label=''):
    return client.post(
        f'/admin/province-maps/{prov.id}/create',
        data={'source_site': '', 'source_url': '', 'label': label,
              'image_file': (io.BytesIO(data_bytes), filename)},
        content_type='multipart/form-data',
        follow_redirects=True,
    )


class TestModels:
    def test_multiple_maps_per_province_allowed(self, db_session):
        prov, _ = make_province(db_session)
        db_session.add(ProvinceMap(location_id=prov.id, filename='a.png',
                                   label='North part'))
        db_session.add(ProvinceMap(location_id=prov.id, filename='b.png',
                                   label='South part'))
        db_session.flush()
        assert ProvinceMap.query.filter_by(location_id=prov.id).count() == 2

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

    def test_same_location_placeable_on_sibling_maps(self, db_session):
        prov, _ = make_province(db_session)
        child = factories.make_location(name='Spanning', parent_id=prov.id)
        m1 = ProvinceMap(location_id=prov.id, filename='a.png')
        m2 = ProvinceMap(location_id=prov.id, filename='b.png')
        db_session.add_all([m1, m2])
        db_session.flush()
        db_session.add(ProvinceMapPlacement(
            province_map_id=m1.id, location_id=child.id,
            kind='point', geometry=[1, 1]))
        db_session.add(ProvinceMapPlacement(
            province_map_id=m2.id, location_id=child.id,
            kind='point', geometry=[9, 9]))
        db_session.flush()
        assert ProvinceMapPlacement.query.count() == 2

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

    def test_display_label(self, db_session):
        assert ProvinceMap(location_id=1, filename='x.png',
                           label='North').display_label == 'North'
        assert ProvinceMap(location_id=1, filename='x.png',
                           label='').display_label == 'Map'

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


class TestListPage:
    def test_lists_only_provinces(self, admin_client, db_session):
        client, _ = admin_client
        make_province(db_session, name='Listed Province')
        factories.make_location(name='Not A Province')
        db_session.flush()
        resp = client.get('/admin/province-maps')
        assert resp.status_code == 200
        assert b'Listed Province' in resp.data
        assert b'Not A Province' not in resp.data

    def test_no_maps_state(self, admin_client, db_session):
        client, _ = admin_client
        make_province(db_session, name='Unmapped Province')
        db_session.flush()
        resp = client.get('/admin/province-maps')
        assert b'No maps yet.' in resp.data
        assert b'+ Add map' in resp.data
        assert b'Edit locations' not in resp.data

    def test_multiple_maps_listed_with_labels(self, admin_client,
                                              db_session, app):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Split Province')
        factories.make_location(name='Split Child', parent_id=prov.id)
        db_session.commit()
        assert b'Added map' in create_map(client, prov,
                                          label='North part').data
        create_map(client, prov, label='South part')
        maps = ProvinceMap.query.filter_by(location_id=prov.id).all()
        assert len(maps) == 2
        for m in maps:
            assert m.filename == f'{prov.id}_{m.id}.png'
            assert os.path.exists(os.path.join(
                app.static_folder, 'provincemaps', m.filename))
        # Descendant counting is deep: add a grandchild too.
        split_child = Location.query.filter_by(name='Split Child').one()
        factories.make_location(name='Split Grandchild',
                                parent_id=split_child.id)
        db_session.commit()
        resp = client.get('/admin/province-maps')
        assert b'North part' in resp.data
        assert b'South part' in resp.data
        assert resp.data.count(b'Edit locations') == 2
        assert b'2 child locations' in resp.data

    def test_create_requires_file(self, admin_client, db_session):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Fileless Province')
        db_session.commit()
        resp = client.post(
            f'/admin/province-maps/{prov.id}/create',
            data={'source_site': '', 'source_url': '', 'label': 'x'},
            content_type='multipart/form-data', follow_redirects=True)
        assert b'Choose an image file' in resp.data
        assert ProvinceMap.query.count() == 0

    def test_create_rejects_garbage(self, admin_client, db_session):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Garbage Province')
        db_session.commit()
        resp = create_map(client, prov, b'<?php nope', 'map.png')
        assert b'look like a real image' in resp.data
        assert ProvinceMap.query.count() == 0

    def test_create_rejects_non_province(self, admin_client, db_session):
        client, _ = admin_client
        loc = factories.make_location(name='Plain Loc')
        db_session.commit()
        resp = client.post(
            f'/admin/province-maps/{loc.id}/create',
            data={'label': '', 'source_site': '', 'source_url': '',
                  'image_file': (io.BytesIO(PNG), 'map.png')},
            content_type='multipart/form-data')
        assert resp.status_code == 404

    def test_update_label_without_file(self, admin_client, db_session):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Update Province')
        db_session.commit()
        create_map(client, prov, label='Old Label')
        m = ProvinceMap.query.one()
        resp = client.post(
            f'/admin/province-maps/map/{m.id}/update',
            data={'label': 'New Label', 'source_site': 'Somewhere',
                  'source_url': ''},
            content_type='multipart/form-data', follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        assert m.label == 'New Label'
        assert m.source_site == 'Somewhere'

    def test_delete_map_removes_file_and_placements(self, admin_client,
                                                    db_session, app):
        client, _ = admin_client
        prov, _ = make_province(db_session, name='Delete Province')
        child = factories.make_location(parent_id=prov.id)
        db_session.commit()
        create_map(client, prov)
        m = ProvinceMap.query.one()
        client.post(f'/admin/province-maps/map/{m.id}/placements/{child.id}',
                    json={'kind': 'point', 'geometry': [1, 1]})
        path = os.path.join(app.static_folder, 'provincemaps', m.filename)
        assert os.path.exists(path)
        client.post(f'/admin/province-maps/map/{m.id}/delete',
                    follow_redirects=True)
        assert ProvinceMap.query.count() == 0
        assert ProvinceMapPlacement.query.count() == 0
        assert not os.path.exists(path)

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
        create_map(client, prov)
        pmap = ProvinceMap.query.filter_by(location_id=prov.id).one()
        return prov, pmap, county, river, region

    def test_editor_404_for_unknown_map(self, admin_client, db_session):
        client, _ = admin_client
        assert client.get(
            '/admin/province-maps/editor/424242').status_code == 404

    def test_editor_payload(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, river, region = self._setup(client, db_session)
        resp = client.get(f'/admin/province-maps/editor/{pmap.id}')
        assert resp.status_code == 200
        assert b'id="pme-payload"' in resp.data
        assert b'Editor County' in resp.data
        assert b'"point_type": "line"' in resp.data
        assert b'js/province_map_editor.js' in resp.data
        assert b'location_edit_url_template' in resp.data

    def test_editor_list_shows_aliases(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, *_ = self._setup(client, db_session)
        factories.make_location(name='Aliased Spot', parent_id=prov.id,
                                aliases='Old Name,Ye Olde Spot')
        db_session.commit()
        resp = client.get(f'/admin/province-maps/editor/{pmap.id}')
        assert b'Aliased Spot' in resp.data
        assert b'(Old Name,Ye Olde Spot)' in resp.data

    def test_deep_descendants_included(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, *_ = self._setup(client, db_session)
        # river inside a commandery inside the province — 3 levels deep.
        commandery = factories.make_location(name='Deep Commandery',
                                             parent_id=prov.id)
        deep_river = factories.make_location(name='Deep Nested River',
                                             parent_id=commandery.id)
        db_session.commit()
        resp = client.get(f'/admin/province-maps/editor/{pmap.id}')
        assert b'Deep Nested River' in resp.data
        assert b'Deep Commandery' in resp.data   # crumb + own row
        # And it's placeable.
        r = client.post(
            f'/admin/province-maps/map/{pmap.id}/placements/{deep_river.id}',
            json={'kind': 'point', 'geometry': [5, 5]})
        assert r.status_code == 200

    def test_editor_sibling_switcher(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, *_ = self._setup(client, db_session)
        create_map(client, prov, label='South part')
        other = ProvinceMap.query.filter_by(
            location_id=prov.id, label='South part').one()
        resp = client.get(f'/admin/province-maps/editor/{pmap.id}')
        assert f'/admin/province-maps/editor/{other.id}'.encode() in resp.data
        assert b'South part' in resp.data

    def test_place_point_line_region(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, river, region = self._setup(client, db_session)
        base = f'/admin/province-maps/map/{pmap.id}/placements'
        r = client.post(f'{base}/{county.id}',
                        json={'kind': 'point', 'geometry': [100.5, 200.25]})
        assert r.status_code == 200 and r.get_json()['created'] is True
        r = client.post(f'{base}/{river.id}',
                        json={'kind': 'line',
                              'geometry': [[1, 2], [3, 4], [5, 6]]})
        assert r.status_code == 200
        r = client.post(f'{base}/{region.id}',
                        json={'kind': 'region',
                              'geometry': [[0, 0], [10, 0], [10, 10]]})
        assert r.status_code == 200
        assert ProvinceMapPlacement.query.count() == 3

    def test_placements_independent_per_map(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, *_ = self._setup(client, db_session)
        create_map(client, prov, label='South part')
        other = ProvinceMap.query.filter_by(
            location_id=prov.id, label='South part').one()
        client.post(f'/admin/province-maps/map/{pmap.id}/placements/{county.id}',
                    json={'kind': 'point', 'geometry': [1, 1]})
        client.post(f'/admin/province-maps/map/{other.id}/placements/{county.id}',
                    json={'kind': 'point', 'geometry': [9, 9]})
        rows = ProvinceMapPlacement.query.order_by(
            ProvinceMapPlacement.province_map_id).all()
        assert len(rows) == 2
        assert {r.province_map_id for r in rows} == {pmap.id, other.id}

    def test_place_upserts(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, *_ = self._setup(client, db_session)
        url = f'/admin/province-maps/map/{pmap.id}/placements/{county.id}'
        client.post(url, json={'kind': 'point', 'geometry': [1, 1]})
        r = client.post(url, json={'kind': 'point', 'geometry': [9, 9]})
        assert r.get_json()['created'] is False
        pl = ProvinceMapPlacement.query.one()
        assert pl.geometry == [9, 9]

    def test_kind_must_match_type(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, river, _ = self._setup(client, db_session)
        r = client.post(
            f'/admin/province-maps/map/{pmap.id}/placements/{river.id}',
            json={'kind': 'point', 'geometry': [1, 1]})
        assert r.status_code == 400
        assert 'does not match' in r.get_json()['error']

    def test_geometry_shape_validated(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, river, region = self._setup(client, db_session)
        bad = [
            (county, {'kind': 'point', 'geometry': [1]}),
            (county, {'kind': 'point', 'geometry': 'nope'}),
            (river, {'kind': 'line', 'geometry': [[1, 2]]}),
            (region, {'kind': 'region', 'geometry': [[1, 2], [3, 4]]}),
        ]
        for loc, body in bad:
            r = client.post(
                f'/admin/province-maps/map/{pmap.id}/placements/{loc.id}',
                json=body)
            assert r.status_code == 400, (loc.name, body)

    def test_foreign_child_rejected(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, *_ = self._setup(client, db_session)
        outsider = factories.make_location(name='Outsider Loc')
        db_session.commit()
        r = client.post(
            f'/admin/province-maps/map/{pmap.id}/placements/{outsider.id}',
            json={'kind': 'point', 'geometry': [1, 1]})
        assert r.status_code == 400

    def test_delete_placement(self, admin_client, db_session):
        client, _ = admin_client
        prov, pmap, county, *_ = self._setup(client, db_session)
        base = f'/admin/province-maps/map/{pmap.id}/placements/{county.id}'
        client.post(base, json={'kind': 'point', 'geometry': [1, 1]})
        r = client.post(f'{base}/delete', json={})
        assert r.status_code == 200
        assert ProvinceMapPlacement.query.count() == 0
        r = client.post(f'{base}/delete', json={})
        assert r.status_code == 404
