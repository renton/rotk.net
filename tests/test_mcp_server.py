"""rotk-net MCP server — protocol handshake, tool dispatch, gap sweeps.

The server is a standalone stdio program (mcp_server/rotk_mcp.py); we
import it as a module and monkeypatch its HTTP layer, so these tests
never touch the network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..',
                                'mcp_server'))
import rotk_mcp  # noqa: E402


@pytest.fixture()
def fake_api(monkeypatch):
    """Replace rotk_mcp.api_get with a canned-response recorder."""
    calls = []
    responses = {}

    def fake_get(path, params=None):
        calls.append((path, dict(params or {})))
        key = (path, json.dumps(params or {}, sort_keys=True))
        if key in responses:
            return responses[key]
        return responses.get(path, {'error': 'no canned response',
                                    'path': path})

    monkeypatch.setattr(rotk_mcp, 'api_get', fake_get)
    return {'calls': calls, 'responses': responses}


def rpc(method, params=None, msg_id=1):
    msg = {'jsonrpc': '2.0', 'method': method}
    if msg_id is not None:
        msg['id'] = msg_id
    if params is not None:
        msg['params'] = params
    return rotk_mcp.handle_message(msg)


def tool(name, arguments, fake=None):
    resp = rpc('tools/call', {'name': name, 'arguments': arguments})
    body = resp['result']['content'][0]['text']
    return resp['result']['isError'], json.loads(body) if body.startswith(
        ('{', '[')) else body


class TestProtocol:
    def test_initialize_echoes_protocol_version(self):
        resp = rpc('initialize', {'protocolVersion': '2025-06-18'})
        assert resp['result']['protocolVersion'] == '2025-06-18'
        assert resp['result']['serverInfo']['name'] == 'rotk-net'
        assert 'tools' in resp['result']['capabilities']

    def test_initialized_notification_silent(self):
        msg = {'jsonrpc': '2.0', 'method': 'notifications/initialized'}
        assert rotk_mcp.handle_message(msg) is None

    def test_tools_list_schemas(self):
        resp = rpc('tools/list')
        tools = resp['result']['tools']
        assert [t['name'] for t in tools] == [
            'rotk_api_index', 'rotk_list', 'rotk_get',
            'rotk_find_data_gaps', 'rotk_fetch']
        for t in tools:
            assert t['inputSchema']['type'] == 'object'
            assert t['description']
        list_schema = tools[1]['inputSchema']
        assert set(rotk_mcp.RESOURCES) == \
            set(list_schema['properties']['resource']['enum'])

    def test_unknown_method_error(self):
        resp = rpc('definitely/not/a/method')
        assert resp['error']['code'] == -32601

    def test_unknown_notification_silent(self):
        msg = {'jsonrpc': '2.0', 'method': 'weird/notification'}
        assert rotk_mcp.handle_message(msg) is None

    def test_selftest_passes(self, capsys):
        rotk_mcp.selftest()
        assert 'selftest OK' in capsys.readouterr().out


class TestToolDispatch:
    def test_list_builds_path_and_params(self, fake_api):
        fake_api['responses']['/api/v1/characters'] = {'items': [],
                                                       'total': 0}
        is_err, body = tool('rotk_list', {
            'resource': 'characters',
            'params': {'q': 'Cao', 'sort': 'mentions'},
            'page': 2, 'per_page': 10})
        assert is_err is False
        path, params = fake_api['calls'][0]
        assert path == '/api/v1/characters'
        assert params == {'q': 'Cao', 'sort': 'mentions',
                          'page': 2, 'per_page': 10}

    def test_get_maps_resource_to_detail_path(self, fake_api):
        fake_api['responses']['/api/v1/chapters/60'] = {'chapter_num': 60}
        is_err, body = tool('rotk_get', {'resource': 'chapters', 'id': 60})
        assert is_err is False
        assert fake_api['calls'][0][0] == '/api/v1/chapters/60'
        assert body['chapter_num'] == 60

    def test_unknown_resource_reported(self, fake_api):
        is_err, body = tool('rotk_list', {'resource': 'users'})
        assert body['error'].startswith('Unknown resource')
        assert fake_api['calls'] == []   # nothing fetched

    def test_fetch_guards_path_prefix(self, fake_api):
        is_err, body = tool('rotk_fetch', {'path': '/admin/users'})
        assert 'Only' in body['error']
        assert fake_api['calls'] == []
        fake_api['responses']['/api/v1/tags?q=x'] = {'items': []}
        is_err, body = tool('rotk_fetch', {'path': '/api/v1/tags?q=x'})
        assert is_err is False

    def test_unknown_tool_is_error(self):
        resp = rpc('tools/call', {'name': 'rotk_write_everything',
                                  'arguments': {}})
        assert resp['result']['isError'] is True

    def test_server_never_uses_write_http_methods(self):
        # The module must not reference any write verb on its session —
        # the MCP layer is read-only by construction.
        src = open(rotk_mcp.__file__).read()
        for verb in ('session.post', 'session.put', 'session.patch',
                     'session.delete', 'requests.post', 'requests.put',
                     'requests.delete'):
            assert verb not in src


class TestGapSweeps:
    def test_characters_without_faction_pages_through(self, fake_api):
        page1 = {'items': [
            {'id': 1, 'name': 'Has Faction',
             'factions': [{'id': 9}], 'primary_faction': None},
            {'id': 2, 'name': 'No Faction',
             'factions': [], 'primary_faction': None},
        ], 'pages': 2, 'total': 3}
        page2 = {'items': [
            {'id': 3, 'name': 'Also Bare',
             'factions': [], 'primary_faction': None},
        ], 'pages': 2, 'total': 3}
        fake_api['responses'][('/api/v1/characters',
                               json.dumps({'page': 1, 'per_page': 100},
                                          sort_keys=True))] = page1
        fake_api['responses'][('/api/v1/characters',
                               json.dumps({'page': 2, 'per_page': 100},
                                          sort_keys=True))] = page2
        is_err, body = tool('rotk_find_data_gaps',
                            {'check': 'characters_without_faction'})
        assert is_err is False
        assert body['total_scanned'] == 3
        assert [h['id'] for h in body['hits']] == [2, 3]

    def test_chapters_with_unparsed_dates(self, fake_api):
        fake_api['responses'][('/api/v1/chapters',
                               json.dumps({'page': 1, 'per_page': 100},
                                          sort_keys=True))] = {
            'items': [
                {'chapter_num': 1, 'title': 'Fine',
                 'date': {'raw': '208'}, 'years': [208]},
                {'chapter_num': 2, 'title': 'Broken',
                 'date': {'raw': 'sometime in spring'}, 'years': []},
                {'chapter_num': 3, 'title': 'Undated',
                 'date': {'raw': ''}, 'years': []},
            ], 'pages': 1}
        is_err, body = tool('rotk_find_data_gaps',
                            {'check': 'chapters_with_unparsed_dates'})
        assert body['hit_count'] == 1
        assert body['hits'][0]['id'] == 2
        assert 'sometime in spring' in body['hits'][0]['detail']

    def test_year_maps_missing_years(self, fake_api):
        have = [{'year': y} for y in range(184, 281) if y != 200]
        fake_api['responses'][('/api/v1/year-maps',
                               json.dumps({'per_page': 100},
                                          sort_keys=True))] = {
            'items': have, 'pages': 1}
        is_err, body = tool('rotk_find_data_gaps',
                            {'check': 'year_maps_missing_years'})
        assert body['missing_years'] == [200]

    def test_province_maps_without_placements(self, fake_api):
        fake_api['responses'][('/api/v1/province-maps',
                               json.dumps({'page': 1, 'per_page': 100},
                                          sort_keys=True))] = {
            'items': [
                {'id': 1, 'name': None, 'label': 'North',
                 'placement_count': 3},
                {'id': 2, 'name': None, 'label': 'South',
                 'placement_count': 0},
            ], 'pages': 1}
        is_err, body = tool('rotk_find_data_gaps',
                            {'check': 'province_maps_without_placements'})
        assert body['hit_count'] == 1
        assert body['hits'][0]['id'] == 2

    def test_unknown_check_lists_available(self, fake_api):
        is_err, body = tool('rotk_find_data_gaps', {'check': 'nonsense'})
        assert 'available' in body
        assert 'characters_without_faction' in body['available']
