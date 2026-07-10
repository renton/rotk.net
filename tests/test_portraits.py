"""B2-1 — portrait upload (defence-in-depth path) + image admin."""
import io

from app.models import Tag, TagAssociation
from app.models.character import Portrait
from app.blueprints.main.views import _detect_image_type
from tests import factories

# Minimal valid-signature byte blobs.
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPG = b'\xff\xd8\xff\xe0' + b'\x00' * 64
GIF = b'GIF89a' + b'\x00' * 64
WEBP = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 64


class TestDetectImageType:
    def test_png(self):
        assert _detect_image_type(PNG[:12]) == 'png'

    def test_jpg(self):
        assert _detect_image_type(JPG[:12]) == 'jpg'

    def test_gif(self):
        assert _detect_image_type(GIF[:12]) == 'gif'

    def test_webp(self):
        assert _detect_image_type(WEBP[:12]) == 'webp'

    def test_garbage_is_none(self):
        assert _detect_image_type(b'<?php evil') is None

    def test_empty_is_none(self):
        assert _detect_image_type(b'') is None


class TestUploadPortrait:
    def _upload(self, client, character, data_bytes=PNG, filename='pic.png',
                **extra):
        data = {
            'image_file': (io.BytesIO(data_bytes), filename),
            'source_site': '', 'source_url': '', 'tag_name': '',
        }
        data.update(extra)
        return client.post(f'/characters/{character.id}/upload-portrait',
                           data=data, content_type='multipart/form-data',
                           follow_redirects=True)

    def test_valid_png_upload(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        resp = self._upload(client, c)
        assert resp.status_code == 200
        p = Portrait.query.filter_by(character_id=c.id).first()
        assert p is not None
        assert p.filename.endswith('.png')
        assert p.is_hidden is True   # visible unchecked in this post

    def test_extension_mismatch_refused(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        # PNG bytes declared as .jpg → refused.
        self._upload(client, c, data_bytes=PNG, filename='sneaky.jpg')
        assert Portrait.query.filter_by(character_id=c.id).count() == 0

    def test_non_image_bytes_refused(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        self._upload(client, c, data_bytes=b'#!/bin/sh\nrm -rf /' * 4,
                     filename='script.png')
        assert Portrait.query.filter_by(character_id=c.id).count() == 0

    def test_disallowed_extension_refused(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        self._upload(client, c, data_bytes=PNG, filename='vector.svg')
        assert Portrait.query.filter_by(character_id=c.id).count() == 0

    def test_source_credit_stored(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        self._upload(client, c, source_site='Wikipedia',
                     source_url='https://wiki.example/x')
        p = Portrait.query.filter_by(character_id=c.id).first()
        assert p.source_site == 'Wikipedia'
        assert p.source_url == 'https://wiki.example/x'

    def test_source_defaults_to_manual_upload(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        self._upload(client, c)
        p = Portrait.query.filter_by(character_id=c.id).first()
        assert p.source_site == 'Manual upload'

    def test_tag_auto_created_and_attached(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        self._upload(client, c, tag_name='FanArt')
        p = Portrait.query.filter_by(character_id=c.id).first()
        tag = Tag.query.filter_by(name='FanArt').first()
        assert tag is not None
        assoc = TagAssociation.query.filter_by(
            tag_id=tag.id, target_type='portrait', target_id=p.id).first()
        assert assoc is not None

    def test_set_default_on_upload_unhides(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        self._upload(client, c, is_default='y')
        p = Portrait.query.filter_by(character_id=c.id).first()
        assert p.is_default is True
        assert p.is_hidden is False   # defaults are always public

    def test_second_default_upload_demotes_first(self, admin_client,
                                                 db_session):
        client, _ = admin_client
        c = factories.make_character()
        old = factories.make_portrait(character=c, is_default=True,
                                      is_hidden=False)
        self._upload(client, c, is_default='y')
        db_session.expire_all()
        assert Portrait.query.get(old.id).is_default is False
        new = Portrait.query.filter_by(character_id=c.id,
                                       is_default=True).first()
        assert new is not None and new.id != old.id

    def test_upload_requires_admin(self, user_client, db_session):
        client, _ = user_client
        c = factories.make_character()
        resp = client.post(f'/characters/{c.id}/upload-portrait', data={},
                           content_type='multipart/form-data')
        assert resp.status_code == 403


class TestImageAdminRoutes:
    def test_image_manager_renders(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        factories.make_portrait(character=c)
        resp = client.get('/admin/images')
        assert resp.status_code == 200

    def test_set_default_route(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        p = factories.make_portrait(character=c)   # hidden by default
        client.post(f'/admin/images/{p.id}/set-default',
                    follow_redirects=True)
        db_session.expire_all()
        refreshed = Portrait.query.get(p.id)
        assert refreshed.is_default is True
        assert refreshed.is_hidden is False

    def test_set_default_demotes_previous(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        old = factories.make_portrait(character=c, is_default=True,
                                      is_hidden=False)
        new = factories.make_portrait(character=c)
        client.post(f'/admin/images/{new.id}/set-default',
                    follow_redirects=True)
        db_session.expire_all()
        assert Portrait.query.get(old.id).is_default is False
        assert Portrait.query.get(new.id).is_default is True

    def test_toggle_hidden(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        p = factories.make_portrait(character=c)   # starts hidden
        client.post(f'/admin/images/{p.id}/toggle-hidden',
                    follow_redirects=True)
        db_session.expire_all()
        assert Portrait.query.get(p.id).is_hidden is False

    def test_hiding_a_default_clears_default(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        p = factories.make_portrait(character=c, is_default=True,
                                    is_hidden=False)
        client.post(f'/admin/images/{p.id}/toggle-hidden',
                    follow_redirects=True)
        db_session.expire_all()
        refreshed = Portrait.query.get(p.id)
        assert refreshed.is_hidden is True
        assert refreshed.is_default is False   # no hidden defaults

    def test_add_and_remove_portrait_tag(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        p = factories.make_portrait(character=c)
        client.post(f'/admin/images/{p.id}/tags/add',
                    data={'tag_name': 'DW9'}, follow_redirects=True)
        tag = Tag.query.filter_by(name='DW9').first()
        assert tag is not None
        assert TagAssociation.query.filter_by(
            tag_id=tag.id, target_type='portrait', target_id=p.id
        ).count() == 1
        client.post(f'/admin/images/{p.id}/tags/{tag.id}/remove',
                    follow_redirects=True)
        assert TagAssociation.query.filter_by(
            tag_id=tag.id, target_type='portrait', target_id=p.id
        ).count() == 0
