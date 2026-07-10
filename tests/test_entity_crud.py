"""T13 — entity CRUD routes (characters, factions, roles, locations,
events, URLs, tag-shaped types)."""
import sqlalchemy as sa

from app.models import (
    Character, Event, EventType, Faction, Location, Role, Tag, Url, UrlType,
)
from tests import factories

COLOURS = {'font_colour': '#ffffff', 'bg_colour': '#123456',
           'border_colour': '#654321'}


class TestCharacterCrud:
    def test_new_character_created(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/characters/new', data={
            'name': 'Brand New Guy',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Character.query.filter_by(name='Brand New Guy').count() == 1

    def test_aliases_normalised_on_save(self, admin_client, db_session):
        client, _ = admin_client
        client.post('/characters/new', data={
            'name': 'Alias Guy', 'aliases': 'One, Two , Three',
        }, follow_redirects=True)
        c = Character.query.filter_by(name='Alias Guy').first()
        assert c.aliases == 'One,Two,Three'

    def test_primary_faction_auto_added_to_m2m(self, admin_client, db_session):
        client, _ = admin_client
        f = factories.make_faction(name='AutoAddFaction')
        client.post('/characters/new', data={
            'name': 'Faction Guy', 'primary_faction': str(f.id),
        }, follow_redirects=True)
        c = Character.query.filter_by(name='Faction Guy').first()
        assert c.primary_faction_id == f.id
        assert f in c.factions.all()

    def test_duplicate_composite_flashes_not_500(self, admin_client,
                                                 db_session):
        client, _ = admin_client
        factories.make_character(name='Dupe', birth_date='1', death_date='2',
                                 ancestral_home='X')
        resp = client.post('/characters/new', data={
            'name': 'Dupe', 'birth_date': '1', 'death_date': '2',
            'ancestral_home': 'X',
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Character.query.filter_by(name='Dupe').count() == 1

    def test_edit_character_label_change_recounts(self, admin_client,
                                                  db_session):
        client, _ = admin_client
        ch = factories.make_chapter(content='<p>Xun Yu advised twice. '
                                            'Xun Yu agreed.</p>')
        c = factories.make_character(name='Xun Yu')
        factories.associate_character(ch, c, keywords='')  # global fallback
        client.post(f'/characters/edit/{c.id}', data={
            'name': 'Xun Yu',
            'aliases': 'The Advisor',
        }, follow_redirects=True)
        db_session.expire_all()
        assert Character.query.get(c.id).book_mention_count == 2


class TestFactionCrud:
    def test_new_faction(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/factions/new', data={
            'name': 'NewFaction', **COLOURS,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Faction.query.filter_by(name='NewFaction').count() == 1

    def test_duplicate_faction_name_flashes(self, admin_client, db_session):
        client, _ = admin_client
        factories.make_faction(name='TakenName')
        resp = client.post('/factions/new', data={
            'name': 'TakenName', **COLOURS,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Faction.query.filter_by(name='TakenName').count() == 1

    def test_invalid_colour_rejected(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/factions/new', data={
            'name': 'BadColour', 'font_colour': 'red',
            'bg_colour': '#123456', 'border_colour': '#123456',
        }, follow_redirects=True)
        assert Faction.query.filter_by(name='BadColour').count() == 0

    def test_merge_faction(self, admin_client, db_session):
        client, _ = admin_client
        src = factories.make_faction(name='SourceF')
        dst = factories.make_faction(name='TargetF')
        c = factories.make_character(name='Loyalist',
                                     primary_faction_id=src.id)
        c.factions.append(src)
        db_session.flush()
        resp = client.post(f'/factions/{src.id}/merge', data={
            'target_faction_id': str(dst.id),
        }, follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        c2 = Character.query.get(c.id)
        assert c2.primary_faction_id == dst.id
        assert dst in c2.factions.all()
        assert Faction.query.get(src.id).is_hidden is True


class TestRoleCrud:
    def test_new_role_exists(self, admin_client, db_session):
        # Bug a0bcb32: /roles/new was missing for a long time.
        client, _ = admin_client
        resp = client.post('/roles/new', data={
            'name': 'newrole', **COLOURS,
        }, follow_redirects=True)
        assert resp.status_code == 200
        assert Role.query.filter_by(name='newrole').count() == 1

    def test_edit_role(self, admin_client, db_session):
        client, _ = admin_client
        r = factories.make_role(name='oldname')
        client.post(f'/roles/edit/{r.id}', data={
            'name': 'renamedrole', **COLOURS,
        }, follow_redirects=True)
        db_session.expire_all()
        assert Role.query.get(r.id).name == 'renamedrole'


class TestLocationCrud:
    def test_new_location_blank_geojson_stays_null(self, admin_client,
                                                   db_session):
        # Bug 11f25f9: populate_obj used to store the raw "" string.
        client, _ = admin_client
        resp = client.post('/locations/new', data={
            'name': 'CleanGeoTown', 'geojson': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        loc = Location.query.filter_by(name='CleanGeoTown').first()
        assert loc is not None
        assert loc.geojson is None

    def test_new_location_valid_polygon_stored_as_dict(self, admin_client,
                                                       db_session):
        client, _ = admin_client
        poly = ('{"type":"Polygon","coordinates":'
                '[[[112.0,34.0],[113.0,34.0],[113.0,35.0],[112.0,34.0]]]}')
        client.post('/locations/new', data={
            'name': 'PolyTown', 'geojson': poly,
        }, follow_redirects=True)
        loc = Location.query.filter_by(name='PolyTown').first()
        assert isinstance(loc.geojson, dict)
        assert loc.geojson['type'] == 'Polygon'

    def test_invalid_geojson_rejected(self, admin_client, db_session):
        client, _ = admin_client
        client.post('/locations/new', data={
            'name': 'BrokenGeoTown', 'geojson': '{not valid json',
        }, follow_redirects=True)
        assert Location.query.filter_by(name='BrokenGeoTown').count() == 0

    def test_point_geojson_type_rejected(self, admin_client, db_session):
        client, _ = admin_client
        client.post('/locations/new', data={
            'name': 'PointTown',
            'geojson': '{"type":"Point","coordinates":[1,2]}',
        }, follow_redirects=True)
        assert Location.query.filter_by(name='PointTown').count() == 0

    def test_edit_location_cannot_parent_itself(self, admin_client,
                                                db_session):
        client, _ = admin_client
        loc = factories.make_location(name='SelfParent')
        client.post(f'/locations/edit/{loc.id}', data={
            'name': 'SelfParent', 'parent': str(loc.id), 'geojson': '',
        }, follow_redirects=True)
        db_session.expire_all()
        assert Location.query.get(loc.id).parent_id is None

    def test_edit_location_parent_cycle_blocked(self, admin_client,
                                                db_session):
        client, _ = admin_client
        a = factories.make_location(name='CycleA')
        b = factories.make_location(name='CycleB', parent_id=a.id)
        db_session.flush()
        # Making A a child of B would close the loop.
        client.post(f'/locations/edit/{a.id}', data={
            'name': 'CycleA', 'parent': str(b.id), 'geojson': '',
        }, follow_redirects=True)
        db_session.expire_all()
        assert Location.query.get(a.id).parent_id is None


class TestEventCrud:
    def test_new_event_with_type_and_date(self, admin_client, db_session):
        client, _ = admin_client
        et = factories.make_event_type(name='Battle')
        loc = factories.make_location(name='Chibi')
        resp = client.post('/events/new', data={
            'name': 'Red Cliffs Redux',
            'event_type': str(et.id),
            'location': str(loc.id),
            'date': '208 AD',
        }, follow_redirects=True)
        assert resp.status_code == 200
        ev = Event.query.filter_by(name='Red Cliffs Redux').first()
        assert ev.event_type_id == et.id
        assert ev.location_id == loc.id
        assert ev.date == '208 AD'

    def test_edit_event_aliases_normalised(self, admin_client, db_session):
        client, _ = admin_client
        ev = factories.make_event(name='NormMe')
        client.post(f'/events/edit/{ev.id}', data={
            'name': 'NormMe', 'aliases': 'A, B ,C', 'date': '',
        }, follow_redirects=True)
        db_session.expire_all()
        assert Event.query.get(ev.id).aliases == 'A,B,C'


class TestUrlRoutes:
    def test_add_url_to_character(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        resp = client.post(f'/character/{c.id}/urls/add', data={
            'name': 'Wiki', 'url': 'https://example.test/wiki',
            'favicon': '',
        }, follow_redirects=True)
        assert resp.status_code == 200
        u = Url.query.filter_by(target_type='character',
                                target_id=c.id).first()
        assert u is not None
        assert u.url == 'https://example.test/wiki'

    def test_add_url_bad_owner_type_404(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/nonsense/1/urls/add', data={
            'name': 'X', 'url': 'https://example.test',
        })
        assert resp.status_code == 404

    def test_delete_url(self, admin_client, db_session):
        client, _ = admin_client
        c = factories.make_character()
        u = factories.make_url(target_type='character', target_id=c.id)
        resp = client.post(f'/urls/{u.id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        db_session.expire_all()
        refetched = Url.query.get(u.id)
        assert refetched is None or refetched.is_deleted


class TestTagShapedTypesCrud:
    def test_tag_crud(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/admin/tags/new', data={
            'name': 'FreshTag', **COLOURS,
        }, follow_redirects=True)
        assert resp.status_code == 200
        t = Tag.query.filter_by(name='FreshTag').first()
        assert t is not None
        client.post(f'/admin/tags/{t.id}/edit', data={
            'name': 'RenamedTag', **COLOURS,
        }, follow_redirects=True)
        db_session.expire_all()
        assert Tag.query.get(t.id).name == 'RenamedTag'

    def test_url_type_delete_guard_when_in_use(self, admin_client,
                                               db_session):
        client, _ = admin_client
        ut = factories.make_url_type(name='InUseType')
        c = factories.make_character()
        factories.make_url(target_type='character', target_id=c.id,
                           url_type_id=ut.id)
        client.post(f'/admin/url-types/{ut.id}/delete', follow_redirects=True)
        db_session.expire_all()
        assert UrlType.query.get(ut.id) is not None  # refused

    def test_url_type_delete_when_unused(self, admin_client, db_session):
        client, _ = admin_client
        ut = factories.make_url_type(name='UnusedType')
        client.post(f'/admin/url-types/{ut.id}/delete', follow_redirects=True)
        db_session.expire_all()
        assert UrlType.query.get(ut.id) is None

    def test_event_type_delete_guard_when_assigned(self, admin_client,
                                                   db_session):
        client, _ = admin_client
        et = factories.make_event_type(name='AssignedType')
        factories.make_event(event_type_id=et.id)
        client.post(f'/admin/event-types/{et.id}/delete',
                    follow_redirects=True)
        db_session.expire_all()
        assert EventType.query.get(et.id) is not None

    def test_event_type_crud(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.post('/admin/event-types/new', data={
            'name': 'Skirmish', 'icon': 'fa-solid fa-flag', **COLOURS,
        }, follow_redirects=True)
        assert resp.status_code == 200
        et = EventType.query.filter_by(name='Skirmish').first()
        assert et is not None
        assert et.icon == 'fa-solid fa-flag'
