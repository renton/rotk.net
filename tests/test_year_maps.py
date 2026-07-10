"""Yearly Maps — YearMap model + /admin/yearly-maps modal save/remove."""
import io
import os

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import YearMap
from app.models.year_map import YEARMAP_DIR, YEARMAP_FIRST_YEAR, YEARMAP_LAST_YEAR

# Minimal valid-signature byte blobs (same as test_portraits).
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPG = b'\xff\xd8\xff\xe0' + b'\x00' * 64


@pytest.fixture(autouse=True)
def _clean_yearmap_files(app):
    """Remove any files the test created under static/yearmaps.

    DB rows roll back with the savepoint, but file writes don't — snapshot
    the directory before the test and delete anything new afterwards."""
    yearmaps_dir = os.path.join(app.static_folder, YEARMAP_DIR)
    os.makedirs(yearmaps_dir, exist_ok=True)
    before = set(os.listdir(yearmaps_dir))
    yield
    for name in set(os.listdir(yearmaps_dir)) - before:
        os.remove(os.path.join(yearmaps_dir, name))


def _save(client, year, data_bytes=PNG, filename='map.png',
          source_site='', source_url=''):
    """POST the modal form. data_bytes=None posts without a file
    (attribution-only update)."""
    data = {'source_site': source_site, 'source_url': source_url}
    if data_bytes is not None:
        data['image_file'] = (io.BytesIO(data_bytes), filename)
    return client.post(
        f'/admin/yearly-maps/{year}/upload',
        data=data,
        content_type='multipart/form-data',
        follow_redirects=True,
    )


class TestYearMapModel:
    def test_year_unique(self, db_session):
        db_session.add(YearMap(year=200, filename='200.png'))
        db_session.flush()
        db_session.add(YearMap(year=200, filename='200_again.png'))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_static_path(self, db_session):
        m = YearMap(year=208, filename='208.png')
        assert m.static_path == 'yearmaps/208.png'

    def test_attribution_defaults_empty(self, db_session):
        m = YearMap(year=208, filename='208.png')
        db_session.add(m)
        db_session.flush()
        assert m.source_site == ''
        assert m.source_url == ''

    def test_audit_stamp_outside_request(self, db_session):
        m = YearMap(year=220, filename='220.png')
        db_session.add(m)
        db_session.flush()
        assert m.created_by == 'rotk.net_system'


class TestYearlyMapsPage:
    def test_admin_sees_full_year_range(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.get('/admin/yearly-maps')
        assert resp.status_code == 200
        assert f'<strong>{YEARMAP_FIRST_YEAR}</strong>'.encode() in resp.data
        assert f'<strong>{YEARMAP_LAST_YEAR}</strong>'.encode() in resp.data
        # 97 years, none uploaded yet → 97 Upload buttons, no Edit/Remove.
        assert resp.data.count(b'>Upload<') == (
            YEARMAP_LAST_YEAR - YEARMAP_FIRST_YEAR + 1)
        assert b'>Edit<' not in resp.data
        assert b'>Remove<' not in resp.data

    def test_uploaded_year_shows_preview_edit_and_remove(self, admin_client,
                                                         db_session):
        client, _ = admin_client
        _save(client, 208)
        resp = client.get('/admin/yearly-maps')
        assert b'yearmaps/208.png' in resp.data
        assert b'alt="Map of 208 AD"' in resp.data
        assert b'>Edit<' in resp.data
        assert b'>Remove<' in resp.data

    def test_attribution_rendered_as_link(self, admin_client, db_session):
        client, _ = admin_client
        _save(client, 208, source_site='Wikimedia Commons',
              source_url='https://example.org/map208')
        resp = client.get('/admin/yearly-maps')
        assert b'href="https://example.org/map208"' in resp.data
        assert b'Wikimedia Commons' in resp.data

    def test_modal_prefill_attributes_present(self, admin_client, db_session):
        client, _ = admin_client
        _save(client, 208, source_site='Some Atlas')
        resp = client.get('/admin/yearly-maps')
        assert b'data-source-site="Some Atlas"' in resp.data
        assert b'data-has-image="1"' in resp.data

    def test_anonymous_redirected(self, client, db_session):
        resp = client.get('/admin/yearly-maps')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_non_admin_forbidden(self, user_client, db_session):
        client, _ = user_client
        assert client.get('/admin/yearly-maps').status_code == 403


class TestSave:
    def test_valid_png(self, admin_client, db_session, app):
        client, _ = admin_client
        resp = _save(client, 208)
        assert resp.status_code == 200
        assert b'Map for 208 AD uploaded.' in resp.data
        row = YearMap.query.filter_by(year=208).first()
        assert row is not None
        assert row.filename == '208.png'
        assert os.path.exists(
            os.path.join(app.static_folder, YEARMAP_DIR, '208.png'))

    def test_attribution_saved_with_upload(self, admin_client, db_session):
        client, _ = admin_client
        _save(client, 208, source_site='Wikimedia Commons',
              source_url='https://example.org/map208')
        row = YearMap.query.filter_by(year=208).first()
        assert row.source_site == 'Wikimedia Commons'
        assert row.source_url == 'https://example.org/map208'

    def test_attribution_only_update_keeps_image(self, admin_client,
                                                 db_session, app):
        client, _ = admin_client
        _save(client, 208, source_site='Old credit')
        resp = _save(client, 208, data_bytes=None, source_site='New credit',
                     source_url='https://example.org/new')
        assert b'Map for 208 AD attribution updated.' in resp.data
        row = YearMap.query.filter_by(year=208).first()
        assert row.source_site == 'New credit'
        assert row.source_url == 'https://example.org/new'
        assert row.filename == '208.png'
        assert os.path.exists(
            os.path.join(app.static_folder, YEARMAP_DIR, '208.png'))

    def test_replace_changes_extension_and_removes_stale_file(
            self, admin_client, db_session, app):
        client, _ = admin_client
        _save(client, 208, PNG, 'map.png')
        resp = _save(client, 208, JPG, 'map.jpg')
        assert b'Map for 208 AD replaced.' in resp.data
        rows = YearMap.query.filter_by(year=208).all()
        assert len(rows) == 1                       # upsert, not duplicate
        assert rows[0].filename == '208.jpg'
        yearmaps_dir = os.path.join(app.static_folder, YEARMAP_DIR)
        assert os.path.exists(os.path.join(yearmaps_dir, '208.jpg'))
        assert not os.path.exists(os.path.join(yearmaps_dir, '208.png'))

    def test_garbage_bytes_refused(self, admin_client, db_session):
        client, _ = admin_client
        resp = _save(client, 208, b'<?php evil', 'map.png')
        # "doesn't" renders autoescaped (&#39;) — assert the apostrophe-free tail.
        assert b'look like a real image' in resp.data
        assert YearMap.query.filter_by(year=208).first() is None

    def test_extension_mismatch_refused(self, admin_client, db_session):
        client, _ = admin_client
        resp = _save(client, 208, PNG, 'sneaky.jpg')
        assert b'Refusing to save' in resp.data
        assert YearMap.query.filter_by(year=208).first() is None

    def test_empty_file_refused(self, admin_client, db_session):
        client, _ = admin_client
        resp = _save(client, 208, b'', 'map.png')
        assert b'Uploaded file is empty.' in resp.data
        assert YearMap.query.filter_by(year=208).first() is None

    def test_no_file_for_new_year_refused(self, admin_client, db_session):
        client, _ = admin_client
        resp = _save(client, 208, data_bytes=None, source_site='credit only')
        assert b'choose a file to upload' in resp.data
        assert YearMap.query.filter_by(year=208).first() is None

    def test_overlong_attribution_refused(self, admin_client, db_session):
        client, _ = admin_client
        resp = _save(client, 208, source_site='x' * 256)
        assert b'Attribution too long' in resp.data
        assert YearMap.query.filter_by(year=208).first() is None

    def test_year_out_of_range_404(self, admin_client, db_session):
        client, _ = admin_client
        assert _save(client, YEARMAP_FIRST_YEAR - 1).status_code == 404
        assert _save(client, YEARMAP_LAST_YEAR + 1).status_code == 404

    def test_non_admin_forbidden(self, user_client, db_session):
        client, _ = user_client
        resp = client.post(
            '/admin/yearly-maps/208/upload',
            data={'image_file': (io.BytesIO(PNG), 'map.png')},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 403
        assert YearMap.query.filter_by(year=208).first() is None


class TestRemove:
    def test_remove_deletes_row_and_file(self, admin_client, db_session, app):
        client, _ = admin_client
        _save(client, 208)
        path = os.path.join(app.static_folder, YEARMAP_DIR, '208.png')
        assert os.path.exists(path)
        resp = client.post('/admin/yearly-maps/208/remove',
                           follow_redirects=True)
        assert b'Map for 208 AD removed.' in resp.data
        assert YearMap.query.filter_by(year=208).first() is None
        assert not os.path.exists(path)

    def test_remove_year_without_map_404(self, admin_client, db_session):
        client, _ = admin_client
        assert client.post('/admin/yearly-maps/208/remove').status_code == 404

    def test_non_admin_forbidden(self, user_client, db_session):
        client, _ = user_client
        assert client.post('/admin/yearly-maps/208/remove').status_code == 403
