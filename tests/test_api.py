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
