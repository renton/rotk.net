"""B4 — send_email (suppressed mode) + favicon fetcher (mocked HTTP)."""
import pytest

from app import mail
from app.blueprints.auth.emails import send_email
from tests import factories
from tools import favicon_fetcher as ff_mod
from tools.favicon_fetcher import _looks_like_image, _sanitise_host, fetch_favicon

# Real ICO magic captured from en.wikipedia.org/favicon.ico (2026-07-10):
# 00 00 01 00 <count> ... — served as Content-Type
# "image/vnd.microsoft.icon" (NOT the older "image/x-icon").
ICO_BYTES = b'\x00\x00\x01\x00\x03\x000\x30\x10\x00\x01\x00\x04\x00h\x06' + b'\x00' * 24
REAL_ICO_CONTENT_TYPE = 'image/vnd.microsoft.icon'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32


class TestSendEmail:
    def test_suppressed_send_captures_message(self, app, db_session):
        user = factories.make_user(confirmed=False)
        with app.test_request_context():
            token = user.generate_confirmation_token()
            with mail.record_messages() as outbox:
                send_email(user.email, 'Confirm your account',
                           'auth/email/confirm', user=user, token=token)
        assert len(outbox) == 1
        msg = outbox[0]
        assert msg.recipients == [user.email]
        assert msg.subject.startswith('[rotk.net]')
        assert msg.body and msg.html   # both parts rendered

    def test_token_lands_in_body(self, app, db_session):
        user = factories.make_user(confirmed=False)
        with app.test_request_context():
            token = user.generate_reset_token()
            with mail.record_messages() as outbox:
                send_email(user.email, 'Reset your password',
                           'auth/email/reset_password', user=user,
                           token=token)
        assert token in outbox[0].body

    def test_forgot_password_route_sends_suppressed_mail(self, app,
                                                         db_session):
        user = factories.make_user()
        client = app.test_client()
        with mail.record_messages() as outbox:
            client.post('/auth/forgot-password', data={'email': user.email},
                        follow_redirects=True)
        assert len(outbox) == 1
        assert outbox[0].recipients == [user.email]


class TestSanitiseHost:
    def test_plain_host_kept(self):
        assert _sanitise_host('wikipedia.org') == 'wikipedia.org'

    def test_port_and_weird_chars_scrubbed(self):
        out = _sanitise_host('evil.example:8080/../..')
        assert '/' not in out and '..' not in out

    def test_empty(self):
        assert _sanitise_host('') in ('', None)


class TestLooksLikeImage:
    def test_real_wikipedia_content_type_passes(self):
        assert _looks_like_image(REAL_ICO_CONTENT_TYPE, ICO_BYTES)

    def test_octet_stream_falls_back_to_ico_magic(self):
        # Some hosts serve .ico as application/octet-stream — the magic
        # bytes rescue it.
        assert _looks_like_image('application/octet-stream', ICO_BYTES)

    def test_png_bytes_pass(self):
        assert _looks_like_image('image/png', PNG_BYTES)

    def test_html_error_page_rejected(self):
        assert not _looks_like_image('text/html', b'<!DOCTYPE html><html>')


class TestFetchFavicon:
    """Re-patch requests inside the fetcher (the autouse conftest stub
    replaces fetch_favicon itself for everyone else)."""

    class FakeResponse:
        """Mimics the streaming interface fetch_favicon uses:
        requests.get(..., stream=True) then resp.iter_content(8192)."""

        def __init__(self, content, content_type=REAL_ICO_CONTENT_TYPE,
                     status_code=200):
            self.content = content
            self.status_code = status_code
            self.headers = {'Content-Type': content_type}

        def iter_content(self, chunk_size=8192):
            for i in range(0, len(self.content), chunk_size):
                yield self.content[i:i + chunk_size]

    def test_writes_icon_and_returns_relative_path(self, monkeypatch,
                                                   tmp_path):
        monkeypatch.setattr(
            ff_mod.requests, 'get',
            lambda url, **kw: self.FakeResponse(ICO_BYTES))
        out = fetch_favicon('https://wikipedia.org/wiki/Cao_Cao',
                            str(tmp_path))
        assert out is not None
        assert out.startswith('favicons/')
        assert (tmp_path / out).exists()
        assert (tmp_path / out).read_bytes() == ICO_BYTES

    def test_html_error_page_not_saved(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            ff_mod.requests, 'get',
            lambda url, **kw: self.FakeResponse(
                b'<!DOCTYPE html><html>404</html>', content_type='text/html'))
        out = fetch_favicon('https://broken.example/page', str(tmp_path))
        assert out is None

    def test_http_error_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            ff_mod.requests, 'get',
            lambda url, **kw: self.FakeResponse(b'', status_code=404))
        out = fetch_favicon('https://nowhere.example/x', str(tmp_path))
        assert out is None

    def test_network_exception_returns_none(self, monkeypatch, tmp_path):
        def boom(url, **kw):
            raise ff_mod.requests.exceptions.ConnectionError('nope')
        monkeypatch.setattr(ff_mod.requests, 'get', boom)
        out = fetch_favicon('https://offline.example/x', str(tmp_path))
        assert out is None

    def test_dedup_by_host_reuses_existing(self, monkeypatch, tmp_path):
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return self.FakeResponse(ICO_BYTES)

        monkeypatch.setattr(ff_mod.requests, 'get', fake_get)
        first = fetch_favicon('https://wikipedia.org/a', str(tmp_path))
        second = fetch_favicon('https://wikipedia.org/b', str(tmp_path))
        assert first == second
        assert len(calls) == 1   # cached on disk, no second fetch

    def test_garbage_url_returns_none(self, tmp_path):
        assert fetch_favicon('not a url at all', str(tmp_path)) is None
        assert fetch_favicon('', str(tmp_path)) is None


class TestUrlAddUsesStubbedFetcher:
    def test_add_url_with_blank_favicon_no_network(self, admin_client,
                                                   db_session):
        # The autouse conftest stub means this cannot hit the network;
        # the Url row simply gets no favicon.
        client, _ = admin_client
        c = factories.make_character()
        resp = client.post(f'/character/{c.id}/urls/add', data={
            'name': 'NoFav', 'url': 'https://example.test/x', 'favicon': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        from app.models import Url
        u = Url.query.filter_by(target_type='character',
                                target_id=c.id).first()
        assert u is not None
        assert (u.favicon or '') == ''
