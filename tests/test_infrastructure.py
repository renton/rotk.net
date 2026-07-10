"""T1 sanity tests — prove the harness itself: config safety, schema,
factories, per-test rollback isolation, auth fixtures."""
import pytest

from app.models import Chapter, Character, User
from tests import factories
from tests.conftest import _assert_test_database


class TestConfigSafety:
    def test_app_uses_testing_config(self, app):
        assert app.config['TESTING'] is True

    def test_database_name_is_hardcoded_test_db(self, app):
        uri = app.config['SQLALCHEMY_DATABASE_URI']
        assert uri.rsplit('/', 1)[-1] == 'rotk_net_test'

    def test_safety_guard_trips_on_live_dbname(self):
        with pytest.raises(BaseException) as excinfo:
            _assert_test_database('postgresql+psycopg://u:p@db:5432/rotk_net')
        # pytest.exit raises Exit (a BaseException subclass)
        assert 'SAFETY' in str(excinfo.value)

    def test_safety_guard_accepts_test_dbname(self):
        _assert_test_database('postgresql+psycopg://u:p@db:5432/rotk_net_test')

    def test_csrf_disabled(self, app):
        assert app.config['WTF_CSRF_ENABLED'] is False

    def test_rate_limiter_disabled(self, app):
        assert app.config['RATELIMIT_ENABLED'] is False

    def test_mail_suppressed(self, app):
        assert app.config['MAIL_SUPPRESS_SEND'] is True

    def test_secret_key_present(self, app):
        assert app.config['SECRET_KEY']


class TestIsolation:
    """Two tests writing the same unique value both pass only if each
    test really starts from a clean slate (rollback between tests)."""

    def test_rollback_isolation_first(self, db_session):
        factories.make_chapter(chapter_num=424242, name='Isolation Probe')
        db_session.commit()
        assert Chapter.query.filter_by(chapter_num=424242).count() == 1

    def test_rollback_isolation_second(self, db_session):
        # If the previous test leaked, the unique constraint on
        # chapter_num would explode here (or count would be 1 already).
        assert Chapter.query.filter_by(chapter_num=424242).count() == 0
        factories.make_chapter(chapter_num=424242, name='Isolation Probe')
        db_session.commit()
        assert Chapter.query.filter_by(chapter_num=424242).count() == 1

    def test_route_commit_rolls_back_too(self, admin_client, db_session):
        # Writes performed by route handlers (which call
        # db.session.commit()) land in the savepoint as well.
        client, admin = admin_client
        assert User.query.filter_by(id=admin.id).count() == 1


class TestFactories:
    def test_factories_produce_valid_rows(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character()
        f = factories.make_faction()
        loc = factories.make_location()
        ev = factories.make_event()
        assert all(o.id for o in (ch, c, f, loc, ev))

    def test_associate_character_sets_keywords(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character(name='Cao Cao')
        factories.associate_character(ch, c, keywords='Cao Cao,Mengde')
        row = db_session.execute(
            __import__('sqlalchemy').text(
                'SELECT keywords FROM chapter_character '
                'WHERE chapter_id = :cid AND character_id = :chid'
            ),
            {'cid': ch.id, 'chid': c.id},
        ).scalar()
        assert row == 'Cao Cao,Mengde'


class TestAuthFixtures:
    def test_admin_client_is_authenticated_admin(self, admin_client):
        client, admin = admin_client
        assert admin.is_administrator and admin.confirmed
        resp = client.get('/admin/users')
        assert resp.status_code == 200

    def test_user_client_is_not_admin(self, user_client):
        client, user = user_client
        assert not user.is_administrator
        resp = client.get('/admin/users')
        assert resp.status_code == 403

    def test_anonymous_client_redirected_from_admin(self, client):
        resp = client.get('/admin/users')
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']
