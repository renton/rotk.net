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
