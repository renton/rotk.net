"""T9 — auth flows + the admin_required access-control matrix."""
import pytest

from app.models import User
from app.models.auth import AnonymousUser
from tests import factories

# Representative admin-gated GET routes across feature areas.
ADMIN_ROUTES = [
    '/admin/users',
    '/admin/chapter-associations',
    '/admin/event-associations',
    '/admin/location-associations',
    '/admin/chapter-edit',
    '/admin/annotations/public',
    '/admin/annotations/private',
    '/admin/tags',
    '/admin/url-types',
    '/admin/event-types',
    '/admin/edits',
    '/admin/duplicates',
    '/admin/faq',
    '/admin/images',
]


class TestLogin:
    def test_login_ok(self, app, db_session):
        u = factories.make_user()
        client = app.test_client()
        resp = client.post('/auth/login', data={
            'email': u.email, 'password': factories.DEFAULT_PASSWORD,
        })
        assert resp.status_code == 302  # redirect to index

    def test_login_email_case_insensitive(self, app, db_session):
        u = factories.make_user()
        client = app.test_client()
        resp = client.post('/auth/login', data={
            'email': u.email.upper(), 'password': factories.DEFAULT_PASSWORD,
        })
        assert resp.status_code == 302

    def test_login_bad_password(self, app, db_session):
        u = factories.make_user()
        client = app.test_client()
        resp = client.post('/auth/login', data={
            'email': u.email, 'password': 'wrong',
        })
        assert resp.status_code == 200
        assert b'Invalid email or password' in resp.data

    def test_login_unknown_email(self, app, db_session):
        client = app.test_client()
        resp = client.post('/auth/login', data={
            'email': 'ghost@test.example', 'password': 'whatever',
        })
        assert resp.status_code == 200
        assert b'Invalid email or password' in resp.data

    def test_open_redirect_blocked(self, app, db_session):
        u = factories.make_user()
        client = app.test_client()
        resp = client.post('/auth/login?next=https://evil.example',
                           data={'email': u.email,
                                 'password': factories.DEFAULT_PASSWORD})
        assert resp.status_code == 302
        assert 'evil.example' not in resp.headers['Location']

    def test_logout(self, user_client):
        client, user = user_client
        resp = client.get('/auth/logout')
        assert resp.status_code == 302
        # Session is gone: an admin route now redirects to login.
        resp = client.get('/admin/users')
        assert resp.status_code in (302, 403)


class TestRegisterDisabled:
    def test_register_unreachable(self, client):
        resp = client.get('/auth/register')
        assert resp.status_code in (403, 404)


class TestAdminGateMatrix:
    @pytest.mark.parametrize('route', ADMIN_ROUTES)
    def test_anonymous_redirected(self, client, route):
        resp = client.get(route)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    @pytest.mark.parametrize('route', ADMIN_ROUTES)
    def test_non_admin_forbidden(self, user_client, route):
        client, _ = user_client
        assert client.get(route).status_code == 403

    def test_unconfirmed_admin_forbidden(self, app, db_session):
        u = factories.make_user(is_administrator=True, confirmed=False)
        client = app.test_client()
        client.post('/auth/login', data={
            'email': u.email, 'password': factories.DEFAULT_PASSWORD})
        assert client.get('/admin/users').status_code == 403

    def test_confirmed_admin_allowed(self, admin_client):
        client, _ = admin_client
        for route in ('/admin/users', '/admin/faq', '/admin/tags'):
            assert client.get(route).status_code == 200

    def test_admin_edit_pages_gated_on_main_blueprint(self, user_client,
                                                      db_session):
        client, _ = user_client
        c = factories.make_character()
        assert client.get(f'/characters/edit/{c.id}').status_code == 403
        assert client.get('/characters/new').status_code == 403


class TestTokenFlows:
    def test_forgot_password_get(self, client):
        assert client.get('/auth/forgot-password').status_code == 200

    def test_reset_password_with_valid_token(self, app, db_session):
        u = factories.make_user()
        with app.test_request_context():
            token = u.generate_reset_token()
        client = app.test_client()
        resp = client.post(f'/auth/reset-password/{token}', data={
            'password': 'brand new pass 9',
            'password2': 'brand new pass 9',
        })
        assert resp.status_code in (200, 302)
        db_session.expire_all()
        assert User.query.get(u.id).verify_password('brand new pass 9')

    def test_reset_password_garbage_token(self, app, db_session):
        client = app.test_client()
        resp = client.post('/auth/reset-password/garbage', data={
            'password': 'x y z 123', 'password2': 'x y z 123',
        }, follow_redirects=False)
        # Must not 500; typical behaviour is redirect or re-render.
        assert resp.status_code in (200, 302)

    def test_change_password_requires_login(self, client):
        resp = client.get('/auth/change-password')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']

    def test_change_password_flow(self, user_client, db_session):
        client, user = user_client
        resp = client.post('/auth/change-password', data={
            'old_password': factories.DEFAULT_PASSWORD,
            'password': 'changed pass 42',
            'password2': 'changed pass 42',
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        assert User.query.get(user.id).verify_password('changed pass 42')


class TestAnonymousUser:
    def test_flags(self):
        anon = AnonymousUser()
        assert anon.is_administrator is False
        assert anon.confirmed is False
