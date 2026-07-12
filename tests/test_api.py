"""Public read-only JSON API (/api/v1) — envelope, joins, privacy."""
import pytest

from tests import factories

FORBIDDEN_KEYS = {'created_by', 'last_edited_by', 'notes', 'password_hash',
                  'email'}


def assert_no_private_keys(payload):
    """Recursively assert no admin-only keys appear anywhere in a JSON
    payload — the privacy contract every serializer must hold."""
    if isinstance(payload, dict):
        leaked = FORBIDDEN_KEYS & set(payload.keys())
        assert not leaked, f'private key(s) leaked into API payload: {leaked}'
        for v in payload.values():
            assert_no_private_keys(v)
    elif isinstance(payload, list):
        for v in payload:
            assert_no_private_keys(v)


class TestApiFoundations:
    def test_index_lists_endpoints(self, client, db_session):
        resp = client.get('/api/v1/')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['version'] == 'v1'
        keys = {e['key'] for e in data['endpoints']}
        assert {'characters', 'factions', 'events', 'locations', 'chapters',
                'relationships', 'year-maps', 'annotations'} <= keys

    def test_unknown_path_is_json_404(self, client, db_session):
        resp = client.get('/api/v1/definitely-not-a-thing')
        assert resp.status_code == 404
        assert resp.get_json() == {'error': 'Not found.'}

    def test_no_users_or_edits_endpoints(self, client, db_session):
        assert client.get('/api/v1/users').status_code == 404
        assert client.get('/api/v1/edits').status_code == 404

    def test_write_methods_rejected(self, client, db_session):
        resp = client.post('/api/v1/')
        assert resp.status_code == 405
        assert 'read-only' in resp.get_json()['error']

    def test_anonymous_access_allowed(self, client, db_session):
        # No auth of any kind — the API serves the public site's data.
        assert client.get('/api/v1/').status_code == 200


class TestCharactersApi:
    def _seed_full_character(self, db_session):
        """One character wired into every joinable resource."""
        wei = factories.make_faction(name='API Wei')
        shu = factories.make_faction(name='API Shu')
        role = factories.make_role(name='api strategist')
        c = factories.make_character(name='Api Cao', sex='male',
                                     aliases='Mengde, Lord Api',
                                     book_mention_count=42)
        c.set_primary_faction(wei)
        c.factions.append(shu)
        c.roles.append(role)
        kid = factories.make_character(name='Api Kid', sex='female')
        t = factories.make_relationship_type(
            side1_label='Father', side1_label_female='Mother',
            side2_label='Son', side2_label_female='Daughter')
        factories.make_relationship(c, kid, t)
        factories.make_portrait(character=c, is_hidden=False,
                                filename='api_cao.png')
        factories.make_url(target_type='character', target_id=c.id,
                           name='Api Wiki')
        ch = factories.make_chapter(content='<p>Api Cao rides.</p>')
        factories.associate_character(ch, c, keywords='Api Cao,Mengde')
        db_session.flush()
        return c, kid, ch

    def test_list_envelope_and_joins(self, client, db_session):
        c, kid, ch = self._seed_full_character(db_session)
        resp = client.get('/api/v1/characters')
        assert resp.status_code == 200
        data = resp.get_json()
        assert {'items', 'page', 'per_page', 'pages', 'total'} <= set(data)
        assert data['total'] == 2   # Api Cao + Api Kid
        row = next(i for i in data['items'] if i['name'] == 'Api Cao')
        assert row['sex'] == 'male'
        assert row['book_mention_count'] == 42
        assert row['aliases'] == ['Mengde', 'Lord Api']
        assert row['primary_faction']['name'] == 'API Wei'
        assert {f['name'] for f in row['factions']} == {'API Wei', 'API Shu'}
        assert row['roles'][0]['name'] == 'api strategist'
        # Relationship resolved for the OTHER end's sex → Daughter.
        assert row['relationships'][0]['label'] == 'Daughter'
        assert row['relationships'][0]['character']['name'] == 'Api Kid'
        assert row['portraits'][0]['image'].endswith('api_cao.png')
        assert row['urls'][0]['name'] == 'Api Wiki'
        assert row['chapters'][0]['chapter_num'] == ch.chapter_num
        assert row['chapters'][0]['keywords'] == 'Api Cao,Mengde'
        assert_no_private_keys(data)

    def test_detail_matches_list_shape(self, client, db_session):
        c, kid, ch = self._seed_full_character(db_session)
        resp = client.get(f'/api/v1/characters/{c.id}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['name'] == 'Api Cao'
        assert data['relationships'][0]['label'] == 'Daughter'
        assert_no_private_keys(data)

    def test_filters(self, client, db_session):
        wei = factories.make_faction(name='Filter Wei')
        a = factories.make_character(name='Alpha Api')
        b = factories.make_character(name='Beta Api')
        a.factions.append(wei)
        db_session.flush()
        data = client.get(f'/api/v1/characters?faction_id={wei.id}').get_json()
        assert [i['name'] for i in data['items']] == ['Alpha Api']
        data = client.get('/api/v1/characters?q=beta').get_json()
        assert [i['name'] for i in data['items']] == ['Beta Api']
        data = client.get('/api/v1/characters?letter=B').get_json()
        assert [i['name'] for i in data['items']] == ['Beta Api']

    def test_sort_by_mentions(self, client, db_session):
        factories.make_character(name='Quiet Api', book_mention_count=1)
        factories.make_character(name='Loud Api', book_mention_count=500)
        data = client.get(
            '/api/v1/characters?sort=mentions&dir=desc').get_json()
        assert data['items'][0]['name'] == 'Loud Api'

    def test_deleted_character_hidden_and_404(self, client, db_session):
        c = factories.make_character(name='Ghost Api', is_deleted=True)
        db_session.flush()
        data = client.get('/api/v1/characters').get_json()
        assert all(i['name'] != 'Ghost Api' for i in data['items'])
        assert client.get(f'/api/v1/characters/{c.id}').status_code == 404

    def test_bad_int_param_is_json_400(self, client, db_session):
        resp = client.get('/api/v1/characters?faction_id=abc')
        assert resp.status_code == 400
        assert 'must be an integer' in resp.get_json()['error']


class TestFactionsRolesTagsApi:
    def test_factions_list_and_detail(self, client, db_session):
        f = factories.make_faction(name='Api Banner')
        leader = factories.make_character(name='Api Leader')
        member = factories.make_character(name='Api Member')
        f.leaders.append(leader)
        member.factions.append(f)
        leader.factions.append(f)
        factories.make_url(target_type='faction', target_id=f.id,
                           name='Banner Wiki')
        db_session.flush()

        data = client.get('/api/v1/factions').get_json()
        row = next(i for i in data['items'] if i['name'] == 'Api Banner')
        assert row['leaders'][0]['name'] == 'Api Leader'
        assert row['member_count'] == 2
        assert_no_private_keys(data)

        detail = client.get(f'/api/v1/factions/{f.id}').get_json()
        assert {m['name'] for m in detail['members']} == \
            {'Api Leader', 'Api Member'}
        assert detail['urls'][0]['name'] == 'Banner Wiki'
        assert detail['year_map_years'] == []
        assert_no_private_keys(detail)

    def test_hidden_faction_excluded(self, client, db_session):
        f = factories.make_faction(name='Merged Away', is_hidden=True)
        db_session.flush()
        data = client.get('/api/v1/factions').get_json()
        assert all(i['name'] != 'Merged Away' for i in data['items'])
        assert client.get(f'/api/v1/factions/{f.id}').status_code == 404

    def test_roles(self, client, db_session):
        r = factories.make_role(name='api general')
        c = factories.make_character(name='Role Holder')
        c.roles.append(r)
        db_session.flush()
        data = client.get('/api/v1/roles?q=api gen').get_json()
        assert data['items'][0]['character_count'] == 1
        detail = client.get(f'/api/v1/roles/{r.id}').get_json()
        assert detail['characters'][0]['name'] == 'Role Holder'
        assert_no_private_keys(detail)

    def test_tags(self, client, db_session):
        t = factories.make_tag(name='api-tag')
        db_session.flush()
        data = client.get('/api/v1/tags?q=api-tag').get_json()
        assert data['items'][0]['name'] == 'api-tag'
        assert data['items'][0]['usage_count'] == 0
        detail = client.get(f'/api/v1/tags/{t.id}').get_json()
        assert detail['usage_count'] == 0


class TestEventsApi:
    def _seed(self, db_session):
        from app.models import EventType
        from app.models.event import event_faction
        from app import db as _db
        et = EventType(name='Api Battle', factions1_label='Attackers',
                       factions2_label='Defenders')
        db_session.add(et)
        db_session.flush()
        loc = factories.make_location(name='Api Field')
        ev = factories.make_event(name='Api Clash', date='208',
                                  event_type_id=et.id, location_id=loc.id,
                                  aliases='The Clash')
        wei = factories.make_faction(name='Api Attacker')
        shu = factories.make_faction(name='Api Defender')
        _db.session.execute(event_faction.insert().values([
            dict(event_id=ev.id, faction_id=wei.id, side=1),
            dict(event_id=ev.id, faction_id=shu.id, side=2),
        ]))
        ch = factories.make_chapter()
        factories.associate_event(ch, ev, keywords='Api Clash')
        db_session.flush()
        return ev, et, loc, ch

    def test_list_payload(self, client, db_session):
        ev, et, loc, ch = self._seed(db_session)
        data = client.get('/api/v1/events').get_json()
        row = next(i for i in data['items'] if i['name'] == 'Api Clash')
        assert row['date']['raw'] == '208'
        assert row['date']['year_lo'] == 208.0
        assert row['event_type']['name'] == 'Api Battle'
        assert row['location']['name'] == 'Api Field'
        assert row['factions1']['label'] == 'Attackers'
        assert row['factions1']['factions'][0]['name'] == 'Api Attacker'
        assert row['factions2']['factions'][0]['name'] == 'Api Defender'
        assert row['chapters'][0]['chapter_num'] == ch.chapter_num
        assert row['aliases'] == ['The Clash']
        assert_no_private_keys(data)

    def test_filters(self, client, db_session):
        ev, et, loc, ch = self._seed(db_session)
        other = factories.make_event(name='Unrelated Api Event')
        db_session.flush()
        data = client.get(f'/api/v1/events?location_id={loc.id}').get_json()
        assert [i['name'] for i in data['items']] == ['Api Clash']
        data = client.get(
            f'/api/v1/events?chapter_num={ch.chapter_num}').get_json()
        assert [i['name'] for i in data['items']] == ['Api Clash']
        data = client.get(
            f'/api/v1/events?event_type_id={et.id}').get_json()
        assert [i['name'] for i in data['items']] == ['Api Clash']

    def test_detail_and_typeless_labels(self, client, db_session):
        ev = factories.make_event(name='Plain Api Event')
        db_session.flush()
        detail = client.get(f'/api/v1/events/{ev.id}').get_json()
        assert detail['event_type'] is None
        assert detail['factions1']['label'] == 'Factions'
        assert detail['factions1']['factions'] == []

    def test_event_types_endpoint(self, client, db_session):
        from app.models import EventType
        et = EventType(name='Countable Type', factions1_label='Rebels')
        db_session.add(et)
        db_session.flush()
        factories.make_event(event_type_id=et.id)
        data = client.get('/api/v1/event-types?q=Countable').get_json()
        assert data['items'][0]['factions1_label'] == 'Rebels'
        assert data['items'][0]['event_count'] == 1
        detail = client.get(f'/api/v1/event-types/{et.id}').get_json()
        assert detail['event_count'] == 1


class TestLocationsApi:
    def test_list_with_ancestry(self, client, db_session):
        from app.models import LocationType
        lt = LocationType(name='Api Province')
        db_session.add(lt)
        db_session.flush()
        province = factories.make_location(name='Api Yizhou',
                                           location_type_id=lt.id)
        county = factories.make_location(name='Api Chengdu',
                                         parent_id=province.id,
                                         latitude=30.5, longitude=104.0)
        db_session.flush()
        data = client.get('/api/v1/locations?q=Api Chengdu').get_json()
        row = data['items'][0]
        assert row['parent']['name'] == 'Api Yizhou'
        assert [a['name'] for a in row['ancestry']] == ['Api Yizhou']
        assert row['latitude'] == 30.5
        assert row['has_geojson'] is False
        assert 'geojson' not in row   # detail-only field
        assert_no_private_keys(data)

    def test_detail_extras(self, client, db_session):
        province = factories.make_location(name='Api Parent')
        child = factories.make_location(name='Api Child',
                                        parent_id=province.id)
        ev = factories.make_event(name='Api Located Event',
                                  location_id=province.id)
        ch = factories.make_chapter()
        factories.associate_location(ch, province, keywords='Api Parent')
        db_session.flush()
        detail = client.get(f'/api/v1/locations/{province.id}').get_json()
        assert detail['children'][0]['name'] == 'Api Child'
        assert detail['events_here'][0]['name'] == 'Api Located Event'
        assert detail['chapters'][0]['chapter_num'] == ch.chapter_num
        assert detail['geojson'] is None
        assert_no_private_keys(detail)

    def test_geojson_on_detail(self, client, db_session):
        geo = {'type': 'Polygon',
               'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
        loc = factories.make_location(name='Api Poly', geojson=geo)
        db_session.flush()
        detail = client.get(f'/api/v1/locations/{loc.id}').get_json()
        assert detail['geojson']['type'] == 'Polygon'
        assert detail['has_geojson'] is True

    def test_filters(self, client, db_session):
        parent = factories.make_location(name='Api Root')
        factories.make_location(name='Api Leaf', parent_id=parent.id)
        db_session.flush()
        data = client.get(
            f'/api/v1/locations?parent_id={parent.id}').get_json()
        assert [i['name'] for i in data['items']] == ['Api Leaf']

    def test_location_types(self, client, db_session):
        from app.models import LocationType
        lt = LocationType(name='Api Pass')
        db_session.add(lt)
        db_session.flush()
        factories.make_location(location_type_id=lt.id)
        data = client.get('/api/v1/location-types?q=Api Pass').get_json()
        assert data['items'][0]['location_count'] == 1
        detail = client.get(f'/api/v1/location-types/{lt.id}').get_json()
        assert detail['location_count'] == 1


class TestChaptersApi:
    def _seed(self, db_session):
        ch1 = factories.make_chapter(
            name='First <br> Clause', date='208',
            content='<p>Prose one.</p>', chapter_num=9001)
        ch2 = factories.make_chapter(
            name='Second Chapter', content='<p>Prose two.</p>',
            chapter_num=9002)
        c = factories.make_character(name='Chapter Api Guy')
        factories.associate_character(ch1, c, keywords='Chapter Api Guy')
        ev = factories.make_event(name='Chapter Api Event')
        factories.associate_event(ch1, ev, keywords='Chapter Api Event')
        loc = factories.make_location(name='Chapter Api Place')
        factories.associate_location(ch1, loc, keywords='Chapter Api Place')
        factories.make_annotation(chapter=ch1, section_text='Prose one.',
                                  is_public=True)
        factories.make_annotation(chapter=ch1, section_text='Prose one.',
                                  is_public=False)   # private — not counted
        db_session.flush()
        return ch1, ch2

    def test_list_full_content_and_joins(self, client, db_session):
        ch1, ch2 = self._seed(db_session)
        data = client.get('/api/v1/chapters').get_json()
        row = next(i for i in data['items'] if i['chapter_num'] == 9001)
        assert row['title'] == 'First Clause'        # <br> collapsed
        assert row['content'] == '<p>Prose one.</p>' # prose on the LIST
        assert row['years'] == [208]
        assert row['characters'][0]['name'] == 'Chapter Api Guy'
        assert row['characters'][0]['keywords'] == 'Chapter Api Guy'
        assert row['events'][0]['name'] == 'Chapter Api Event'
        assert row['locations'][0]['name'] == 'Chapter Api Place'
        assert row['public_annotation_count'] == 1   # private excluded
        assert row['next_chapter_num'] == 9002
        assert_no_private_keys(data)

    def test_detail_by_chapter_num(self, client, db_session):
        ch1, ch2 = self._seed(db_session)
        detail = client.get('/api/v1/chapters/9002').get_json()
        assert detail['content'] == '<p>Prose two.</p>'
        assert detail['prev_chapter_num'] == 9001
        assert detail['next_chapter_num'] is None
        assert client.get('/api/v1/chapters/424242').status_code == 404

    def test_character_filter(self, client, db_session):
        ch1, ch2 = self._seed(db_session)
        c = factories.make_character(name='Filter Chapter Guy')
        factories.associate_character(ch2, c, keywords='Filter Chapter Guy')
        db_session.flush()
        data = client.get(f'/api/v1/chapters?character_id={c.id}').get_json()
        assert [i['chapter_num'] for i in data['items']] == [9002]

    def test_default_page_size_small(self, client, db_session):
        data = client.get('/api/v1/chapters').get_json()
        assert data['per_page'] == 20


class TestRelationshipsApi:
    def test_list_with_sex_resolved_labels(self, client, db_session):
        t = factories.make_relationship_type(
            name='Api Parent/Child',
            side1_label='Father', side1_label_female='Mother',
            side2_label='Son', side2_label_female='Daughter')
        mum = factories.make_character(name='Api Mum', sex='female')
        boy = factories.make_character(name='Api Boy', sex='male')
        r = factories.make_relationship(mum, boy, t)
        db_session.flush()
        data = client.get('/api/v1/relationships').get_json()
        row = next(i for i in data['items'] if i['id'] == r.id)
        assert row['character1']['name'] == 'Api Mum'
        assert row['character1']['label'] == 'Mother'
        assert row['character2']['label'] == 'Son'
        assert row['type']['is_symmetric'] is False
        assert_no_private_keys(data)

    def test_character_filter(self, client, db_session):
        t = factories.make_relationship_type()
        a = factories.make_character()
        b = factories.make_character()
        outsider = factories.make_character()
        factories.make_relationship(a, b, t)
        db_session.flush()
        data = client.get(
            f'/api/v1/relationships?character_id={a.id}').get_json()
        assert data['total'] == 1
        data = client.get(
            f'/api/v1/relationships?character_id={outsider.id}').get_json()
        assert data['total'] == 0

    def test_relationship_types_endpoint(self, client, db_session):
        t = factories.make_relationship_type(
            name='Api Siblings', side1_label='Brother',
            side1_label_female='Sister', side2_label='')
        a = factories.make_character()
        b = factories.make_character()
        factories.make_relationship(a, b, t)
        db_session.flush()
        data = client.get('/api/v1/relationship-types?q=Api Sib').get_json()
        row = data['items'][0]
        assert row['is_symmetric'] is True
        assert row['side1_label_female'] == 'Sister'
        assert row['usage_count'] == 1
        detail = client.get(
            f'/api/v1/relationship-types/{t.id}').get_json()
        assert detail['usage_count'] == 1


class TestYearMapsApi:
    def test_list_and_detail(self, client, db_session):
        from app.models import YearMap
        f = factories.make_faction(name='Map Api Faction')
        leader = factories.make_character(name='Map Api Leader')
        f.leaders.append(leader)
        m = YearMap(year=8208, filename='8208.png',
                    source_site='Api Atlas',
                    source_url='https://example.org/atlas')
        m.factions = [f]
        db_session.add(m)
        db_session.flush()

        data = client.get('/api/v1/year-maps').get_json()
        row = next(i for i in data['items'] if i['year'] == 8208)
        assert row['image'].endswith('yearmaps/8208.png')
        assert row['source_site'] == 'Api Atlas'
        assert row['factions'][0]['name'] == 'Map Api Faction'
        assert row['factions'][0]['leaders'][0]['name'] == 'Map Api Leader'
        assert_no_private_keys(data)

        detail = client.get('/api/v1/year-maps/8208').get_json()
        assert detail['year'] == 8208
        assert client.get('/api/v1/year-maps/9999').status_code == 404

    def test_year_range_filter(self, client, db_session):
        from app.models import YearMap
        db_session.add(YearMap(year=8300, filename='a.png'))
        db_session.add(YearMap(year=8310, filename='b.png'))
        db_session.flush()
        data = client.get(
            '/api/v1/year-maps?year_from=8305&year_to=8315').get_json()
        assert [i['year'] for i in data['items']] == [8310]


class TestAnnotationsApi:
    def test_public_only_with_thread_key(self, client, db_session):
        ch = factories.make_chapter(content='<p>Annotated api prose.</p>')
        pub = factories.make_annotation(
            chapter=ch, section_text='Annotated api prose.',
            body='public note', is_public=True)
        factories.make_annotation(
            chapter=ch, section_text='Annotated api prose.',
            body='SECRET ADMIN NOTE', is_public=False)
        factories.make_annotation(
            chapter=ch, section_text='Annotated api prose.',
            body='deleted note', is_public=True, is_deleted=True)
        db_session.flush()

        resp = client.get('/api/v1/annotations')
        data = resp.get_json()
        bodies = [i['body'] for i in data['items']]
        assert bodies == ['public note']
        assert b'SECRET ADMIN NOTE' not in resp.data
        row = data['items'][0]
        assert row['chapter_num'] == ch.chapter_num
        assert row['thread_key']            # content-addressed group key
        assert row['author']                # public on chapter pages too
        assert_no_private_keys(data)

    def test_chapter_filter(self, client, db_session):
        ch1 = factories.make_chapter()
        ch2 = factories.make_chapter()
        factories.make_annotation(chapter=ch1, section_text='x',
                                  body='ch1 note', is_public=True)
        factories.make_annotation(chapter=ch2, section_text='y',
                                  body='ch2 note', is_public=True)
        db_session.flush()
        data = client.get(
            f'/api/v1/annotations?chapter_num={ch2.chapter_num}').get_json()
        assert [i['body'] for i in data['items']] == ['ch2 note']


class TestApiExplorerPage:
    def test_admin_page_renders_registry(self, admin_client, db_session):
        client, _ = admin_client
        resp = client.get('/admin/api-explorer')
        assert resp.status_code == 200
        assert b'id="api-endpoints"' in resp.data
        assert b'/api/v1/characters' in resp.data
        assert b'js/api_explorer.js' in resp.data
        assert b'id="api-endpoint"' in resp.data

    def test_gating(self, client, user_client, db_session):
        resp = client.get('/admin/api-explorer')
        assert resp.status_code == 302   # anonymous → login
        uclient, _ = user_client
        assert uclient.get('/admin/api-explorer').status_code == 403


class TestApiIsReadOnly:
    def test_every_api_route_is_get_only(self, app, db_session):
        """Walk the URL map: no /api/v1 rule may accept a write method."""
        for rule in app.url_map.iter_rules():
            if rule.rule.startswith('/api/v1'):
                writes = rule.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}
                assert not writes, f'{rule.rule} allows {writes}'

    def test_write_methods_405_json(self, client, db_session):
        c = factories.make_character()
        db_session.flush()
        for method in ('post', 'put', 'patch', 'delete'):
            resp = getattr(client, method)(f'/api/v1/characters/{c.id}')
            assert resp.status_code == 405
            assert 'read-only' in resp.get_json()['error']


class TestProvinceMapsApi:
    def _seed(self, db_session):
        from app.models import (LocationType, ProvinceMap,
                                ProvinceMapPlacement)
        lt = LocationType.query.filter_by(name='Province').first()
        if lt is None:
            lt = LocationType(name='Province')
            db_session.add(lt)
            db_session.flush()
        prov = factories.make_location(name='Api Province',
                                       location_type_id=lt.id)
        child = factories.make_location(name='Api Pinned County',
                                        parent_id=prov.id)
        m = ProvinceMap(location_id=prov.id, filename='pm_api.png',
                        label='North part', source_site='Api Source')
        db_session.add(m)
        db_session.flush()
        db_session.add(ProvinceMapPlacement(
            province_map_id=m.id, location_id=child.id,
            kind='point', geometry=[12.5, 30.0]))
        db_session.flush()
        return prov, m, child

    def test_list_and_filter(self, client, db_session):
        prov, m, child = self._seed(db_session)
        data = client.get('/api/v1/province-maps').get_json()
        row = next(i for i in data['items'] if i['id'] == m.id)
        assert row['province']['name'] == 'Api Province'
        assert row['label'] == 'North part'
        assert row['image'].endswith('provincemaps/pm_api.png')
        assert row['placement_count'] == 1
        assert 'placements' not in row      # detail-only
        assert_no_private_keys(data)
        data = client.get(
            f'/api/v1/province-maps?location_id={prov.id}').get_json()
        assert data['total'] == 1

    def test_detail_includes_geometry(self, client, db_session):
        prov, m, child = self._seed(db_session)
        detail = client.get(f'/api/v1/province-maps/{m.id}').get_json()
        assert detail['placement_count'] == 1
        pl = detail['placements'][0]
        assert pl['location']['name'] == 'Api Pinned County'
        assert pl['kind'] == 'point'
        assert pl['geometry'] == [12.5, 30.0]
        assert_no_private_keys(detail)
        assert client.get('/api/v1/province-maps/424242').status_code == 404

    def test_location_types_carry_point_type(self, client, db_session):
        from app.models import LocationType
        lt = LocationType(name='Api Riverine', point_type='line')
        db_session.add(lt)
        db_session.flush()
        data = client.get('/api/v1/location-types?q=Api Riverine').get_json()
        assert data['items'][0]['point_type'] == 'line'
        detail = client.get(f'/api/v1/location-types/{lt.id}').get_json()
        assert detail['point_type'] == 'line'
