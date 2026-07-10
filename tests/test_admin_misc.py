"""B2-2 — admin users, duplicates, edits page, chapter-dates,
location-types, location merge, edit-log relationship diffs."""
import sqlalchemy as sa

from app.models import (
    Edit, Event, Location, LocationType, MatchExclusion, Url, User,
)
from tests import factories


class TestUsersAdmin:
    def test_users_page_lists(self, admin_client, db_session):
        client, admin = admin_client
        other = factories.make_user()
        resp = client.get('/admin/users')
        assert resp.status_code == 200
        assert other.username.encode() in resp.data

    def test_new_user_created(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/admin/users/new', data={
            'email': 'made-by-admin@test.example',
            'username': 'madebyadmin',
            'password': 'strong pass 77',
            'password2': 'strong pass 77',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert User.query.filter_by(
            email='made-by-admin@test.example').count() == 1

    def test_toggle_admin_promotes_other(self, admin_client, db_session):
        client, _ = admin_client
        u = factories.make_user()
        client.post(f'/admin/users/{u.id}/toggle-admin',
                    follow_redirects=True)
        db_session.expire_all()
        assert User.query.get(u.id).is_administrator is True

    def test_toggle_admin_self_refused(self, admin_client, db_session):
        client, admin = admin_client
        client.post(f'/admin/users/{admin.id}/toggle-admin',
                    follow_redirects=True)
        db_session.expire_all()
        assert User.query.get(admin.id).is_administrator is True  # unchanged

    def test_delete_user_self_refused(self, admin_client, db_session):
        client, admin = admin_client
        client.post(f'/admin/users/{admin.id}/delete', follow_redirects=True)
        db_session.expire_all()
        assert User.query.get(admin.id) is not None

    def test_delete_other_user(self, admin_client, db_session):
        client, _ = admin_client
        u = factories.make_user()
        client.post(f'/admin/users/{u.id}/delete', follow_redirects=True)
        db_session.expire_all()
        assert User.query.get(u.id) is None


class TestDuplicatesPage:
    def test_duplicate_names_listed(self, admin_client, db_session):
        client, _ = admin_client
        factories.make_character(name='Zhang Liang', birth_date='a')
        factories.make_character(name='Zhang Liang', birth_date='b')
        factories.make_character(name='Unique Person')
        resp = client.get('/admin/duplicates')
        assert resp.status_code == 200
        assert b'Zhang Liang' in resp.data
        assert b'Unique Person' not in resp.data


class TestEditsPage:
    def test_edits_page_shows_activity(self, admin_client, db_session):
        client, _ = admin_client
        factories.make_faction(name='LoggedFaction')
        db_session.flush()
        resp = client.get('/admin/edits')
        assert resp.status_code == 200
        assert b'faction' in resp.data


class TestChapterDatesPage:
    def test_renders(self, admin_client, db_session):
        client, _ = admin_client
        factories.make_chapter(date='208 AD')
        resp = client.get('/admin/chapter-dates')
        assert resp.status_code == 200
        assert b'208 AD' in resp.data


class TestLocationTypesAdmin:
    COLOURS = {'font_colour': '#ffffff', 'bg_colour': '#123456',
               'border_colour': '#654321'}

    def test_crud(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/admin/location-types/new', data={
            'name': 'Fortress', **self.COLOURS,
        }, follow_redirects=True)
        assert resp.status_code == 200
        lt = LocationType.query.filter_by(name='Fortress').first()
        assert lt is not None
        client.post(f'/admin/location-types/{lt.id}/edit', data={
            'name': 'Citadel', **self.COLOURS,
        }, follow_redirects=True)
        db_session.expire_all()
        assert LocationType.query.get(lt.id).name == 'Citadel'

    def test_delete_guard_when_in_use(self, admin_client, db_session):
        client, _ = admin_client
        lt = factories.make_location_type(name='UsedType')
        factories.make_location(location_type_id=lt.id)
        client.post(f'/admin/location-types/{lt.id}/delete',
                    follow_redirects=True)
        db_session.expire_all()
        assert LocationType.query.get(lt.id) is not None

    def test_delete_unused(self, admin_client, db_session):
        client, _ = admin_client
        lt = factories.make_location_type(name='UnusedType')
        client.post(f'/admin/location-types/{lt.id}/delete',
                    follow_redirects=True)
        db_session.expire_all()
        assert LocationType.query.get(lt.id) is None


class TestMergeLocation:
    def _merge(self, client, source, target):
        return client.post(f'/locations/{source.id}/merge', data={
            'target_location_id': str(target.id),
        }, follow_redirects=True)

    def test_chapter_m2m_moves_with_keywords(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        src = factories.make_location(name='Loyang')
        dst = factories.make_location(name='Luoyang')
        factories.associate_location(ch, src, keywords='Loyang')
        self._merge(client, src, dst)
        db_session.expire_all()
        assert dst in ch.locations
        kw = db_session.execute(sa.text(
            'SELECT keywords FROM chapter_location '
            'WHERE chapter_id=:c AND location_id=:l'),
            {'c': ch.id, 'l': dst.id}).scalar()
        assert 'Loyang' in (kw or '')

    def test_event_fk_moves(self, admin_client, db_session):
        client, _ = admin_client
        src = factories.make_location(name='OldPlace')
        dst = factories.make_location(name='NewPlace')
        ev = factories.make_event(location_id=src.id)
        self._merge(client, src, dst)
        db_session.expire_all()
        assert Event.query.get(ev.id).location_id == dst.id

    def test_children_reparented(self, admin_client, db_session):
        client, _ = admin_client
        src = factories.make_location(name='OldParent')
        dst = factories.make_location(name='NewParent')
        child = factories.make_location(name='TheChild', parent_id=src.id)
        self._merge(client, src, dst)
        db_session.expire_all()
        assert Location.query.get(child.id).parent_id == dst.id

    def test_urls_and_exclusions_move(self, admin_client, db_session):
        client, _ = admin_client
        ch = factories.make_chapter()
        src = factories.make_location(name='UrlPlace')
        dst = factories.make_location(name='UrlTarget')
        u = factories.make_url(target_type='location', target_id=src.id)
        ex = factories.make_match_exclusion(
            chapter=ch, target_type='location', target_id=src.id,
            match_text='UrlPlace')
        self._merge(client, src, dst)
        db_session.expire_all()
        assert Url.query.get(u.id).target_id == dst.id
        assert MatchExclusion.query.get(ex.id).target_id == dst.id

    def test_source_soft_deleted_and_alias_added(self, admin_client,
                                                 db_session):
        client, _ = admin_client
        src = factories.make_location(name='GoneName')
        dst = factories.make_location(name='KeptName')
        self._merge(client, src, dst)
        db_session.expire_all()
        assert Location.query.get(src.id).is_deleted is True
        assert 'GoneName' in (Location.query.get(dst.id).aliases or '')


class TestEditLogRelationships:
    def test_m2m_append_logged_as_relationship_change(self, db_session):
        ch = factories.make_chapter()
        c = factories.make_character()
        db_session.flush()
        ch.characters.append(c)
        db_session.flush()
        rows = Edit.query.filter_by(target_type='chapter',
                                    target_id=ch.id, action='update').all()
        rel_changes = [r for r in rows
                       if '_relationships' in (r.changes or {})]
        assert rel_changes, 'M2M append should emit a relationship diff'
