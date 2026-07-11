#!/usr/bin/env python3
"""rotk-net MCP server — read-only tools over the rotk.net public API.

A deliberately dependency-light MCP (Model Context Protocol) server:
stdlib + `requests` only, speaking JSON-RPC 2.0 over stdio (one JSON
message per line). No MCP SDK required, so it runs anywhere Python 3.10+
and requests exist — including this repo's dev machine, uninstalled.

Wire-up for Claude Code lives in the repo-root `.mcp.json`. Config:

    ROTK_API_BASE     base URL of the site (default https://rotk.net)
    ROTK_API_TIMEOUT  per-request timeout seconds (default 30)

Tools (all read-only):
    rotk_api_index      GET /api/v1/ — the endpoint/param catalogue
    rotk_list           paginated list of any resource, with filters
    rotk_get            one resource by id / chapter_num / year
    rotk_find_data_gaps data-quality sweeps (missing factions, undated
                        events, geo-less locations, ...)
    rotk_fetch          escape hatch: GET any /api/v1 path

Diagnostics:
    python3 rotk_mcp.py --selftest   offline protocol handshake check
    python3 rotk_mcp.py --smoke      live GET <base>/api/v1/
"""
import json
import os
import sys

import requests

API_BASE = os.environ.get('ROTK_API_BASE', 'https://rotk.net').rstrip('/')
TIMEOUT = float(os.environ.get('ROTK_API_TIMEOUT', '30'))

SERVER_INFO = {'name': 'rotk-net', 'version': '1.0.0'}
DEFAULT_PROTOCOL_VERSION = '2024-11-05'

RESOURCES = [
    'characters', 'factions', 'roles', 'tags', 'events', 'event-types',
    'locations', 'location-types', 'chapters', 'relationships',
    'relationship-types', 'year-maps', 'annotations',
]

_session = requests.Session()
_session.headers['Accept'] = 'application/json'
_session.headers['User-Agent'] = 'rotk-mcp/1.0'


def log(msg):
    print(f'[rotk-mcp] {msg}', file=sys.stderr, flush=True)


def api_get(path, params=None):
    """GET <base><path>; returns parsed JSON (raises for non-JSON).

    Non-2xx responses still return the body (the API always answers
    JSON errors) with the status attached, so the model sees WHY."""
    url = API_BASE + path
    resp = _session.get(url, params=params or {}, timeout=TIMEOUT)
    try:
        data = resp.json()
    except ValueError:
        data = {'error': f'Non-JSON response ({resp.status_code}) from {url}',
                'body_start': resp.text[:500]}
    if resp.status_code >= 400 and isinstance(data, dict):
        data.setdefault('http_status', resp.status_code)
    return data


# ---------------------------------------------------------------------------
# Data-gap checks. Each entry: resource to sweep + predicate(item) that
# returns a truthy "what's missing" detail string when the item is a hit.
# Adding a check = one new row here (it shows up in the tool enum
# automatically).
# ---------------------------------------------------------------------------

def _unparsed(span):
    """A date_span dict with raw text set but no parsed year."""
    return bool(span and span.get('raw')) and span.get('year_lo') is None


def _default_colours(item):
    cols = (item.get('font_colour'), item.get('bg_colour'),
            item.get('border_colour'))
    return all(c in (None, '', '#ffffff') for c in cols)


GAP_CHECKS = {
    'characters_without_faction': (
        'characters', lambda i: 'no factions at all'
        if not i.get('factions') and not i.get('primary_faction') else None),
    'characters_without_portrait': (
        'characters', lambda i: 'no visible portraits'
        if not i.get('portraits') else None),
    'characters_without_chapters': (
        'characters', lambda i: 'not associated with any chapter'
        if not i.get('chapters') else None),
    'characters_without_relationships': (
        'characters', lambda i: 'no family relationships'
        if not i.get('relationships') else None),
    'characters_with_unparsed_dates': (
        'characters', lambda i:
        ('birth date unparseable: %r' % i['birth']['raw'])
        if _unparsed(i.get('birth'))
        else (('death date unparseable: %r' % i['death']['raw'])
              if _unparsed(i.get('death')) else None)),
    'factions_without_leaders': (
        'factions', lambda i: 'no leaders set'
        if not i.get('leaders') else None),
    'factions_without_colours': (
        'factions', lambda i: 'all colours still default white'
        if _default_colours(i) else None),
    'factions_without_members': (
        'factions', lambda i: 'no member characters'
        if not i.get('member_count') else None),
    'events_without_date': (
        'events', lambda i: 'no date set'
        if not (i.get('date') or {}).get('raw') else None),
    'events_with_unparsed_dates': (
        'events', lambda i:
        ('date unparseable: %r' % i['date']['raw'])
        if _unparsed(i.get('date')) else None),
    'events_without_type': (
        'events', lambda i: 'no event type'
        if not i.get('event_type') else None),
    'events_without_factions': (
        'events', lambda i: 'no factions on either side'
        if not (i.get('factions1') or {}).get('factions')
        and not (i.get('factions2') or {}).get('factions') else None),
    'events_without_location': (
        'events', lambda i: 'no location'
        if not i.get('location') else None),
    'locations_without_geo': (
        'locations', lambda i: 'no lat/lng and no geojson'
        if i.get('latitude') is None and i.get('longitude') is None
        and not i.get('has_geojson') else None),
    'locations_without_type': (
        'locations', lambda i: 'no location type'
        if not i.get('location_type') else None),
    'locations_without_parent': (
        'locations', lambda i: 'no parent location'
        if not i.get('parent') else None),
    'chapters_without_date': (
        'chapters', lambda i: 'no date set'
        if not (i.get('date') or {}).get('raw') else None),
    'chapters_with_unparsed_dates': (
        'chapters', lambda i:
        ('date set but unparseable: %r' % i['date']['raw'])
        if (i.get('date') or {}).get('raw') and not i.get('years')
        else None),
    'year_maps_without_factions': (
        'year-maps', lambda i: 'no factions attached'
        if not i.get('factions') else None),
}

# Special check that isn't a per-item predicate: which era years have no
# uploaded map at all.
YEARMAP_RANGE = (184, 280)


def _sweep(resource, predicate):
    """Page through a list endpoint and collect predicate hits."""
    hits, page, scanned = [], 1, 0
    while True:
        data = api_get(f'/api/v1/{resource}',
                       {'page': page, 'per_page': 100})
        if 'items' not in data:
            return data, scanned   # error payload — surface as-is
        for item in data['items']:
            scanned += 1
            detail = predicate(item)
            if detail:
                hits.append({
                    'id': item.get('id', item.get('chapter_num',
                                                  item.get('year'))),
                    'name': item.get('name', item.get('title',
                                                      item.get('year'))),
                    'detail': detail,
                })
        if page >= (data.get('pages') or 1):
            break
        page += 1
    return hits, scanned


def find_data_gaps(check):
    if check == 'year_maps_missing_years':
        data = api_get('/api/v1/year-maps', {'per_page': 100})
        if 'items' not in data:
            return data
        have = {i['year'] for i in data['items']}
        missing = [y for y in range(YEARMAP_RANGE[0], YEARMAP_RANGE[1] + 1)
                   if y not in have]
        return {'check': check, 'total_scanned': len(have),
                'hit_count': len(missing), 'missing_years': missing}
    if check not in GAP_CHECKS:
        return {'error': f'Unknown check {check!r}',
                'available': sorted(GAP_CHECKS) + ['year_maps_missing_years']}
    resource, predicate = GAP_CHECKS[check]
    hits, scanned = _sweep(resource, predicate)
    if isinstance(hits, dict):   # error payload from _sweep
        return hits
    return {'check': check, 'resource': resource, 'total_scanned': scanned,
            'hit_count': len(hits), 'hits': hits}


# ---------------------------------------------------------------------------
# Tool definitions + dispatch
# ---------------------------------------------------------------------------

TOOLS = [
    {
        'name': 'rotk_api_index',
        'description': (
            'The rotk.net API catalogue: every endpoint, its query params '
            'and what its payload joins in. Call this first when unsure '
            'which filters exist.'),
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'rotk_list',
        'description': (
            'List a rotk.net resource (paginated envelope: items/page/'
            'per_page/pages/total). `params` takes the endpoint-specific '
            'filters from rotk_api_index, e.g. {"q": "Cao", "sort": '
            '"mentions"} for characters or {"chapter_num": 60} for events.'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'resource': {'type': 'string', 'enum': RESOURCES},
                'params': {'type': 'object',
                           'description': 'Endpoint-specific query filters.'},
                'page': {'type': 'integer', 'minimum': 1},
                'per_page': {'type': 'integer', 'minimum': 1,
                             'maximum': 100},
            },
            'required': ['resource'],
        },
    },
    {
        'name': 'rotk_get',
        'description': (
            'Fetch ONE resource with its full joined payload. `id` is the '
            'row id — except chapters (use the chapter number, 1-120) and '
            'year-maps (use the year, 184-280). Relationships and '
            'annotations have no detail endpoint; use rotk_list filters.'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'resource': {
                    'type': 'string',
                    'enum': [r for r in RESOURCES
                             if r not in ('relationships', 'annotations')]},
                'id': {'type': 'integer'},
            },
            'required': ['resource', 'id'],
        },
    },
    {
        'name': 'rotk_find_data_gaps',
        'description': (
            'Sweep a whole resource for data-quality gaps and return the '
            'offending rows (id, name, what is missing). Use to find '
            'cleanup work: characters without factions/portraits, undated '
            'or unparseable-date events/chapters, geo-less locations, '
            'leaderless factions, era years without territory maps, etc.'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'check': {'type': 'string',
                          'enum': sorted(GAP_CHECKS)
                          + ['year_maps_missing_years']},
            },
            'required': ['check'],
        },
    },
    {
        'name': 'rotk_fetch',
        'description': (
            'Escape hatch: GET any /api/v1 path (with querystring) and '
            'return the JSON. Only /api/v1 paths are allowed.'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string',
                         'description': "e.g. '/api/v1/characters?q=Cao'"},
            },
            'required': ['path'],
        },
    },
]


def call_tool(name, args):
    if name == 'rotk_api_index':
        return api_get('/api/v1/')
    if name == 'rotk_list':
        resource = args['resource']
        if resource not in RESOURCES:
            return {'error': f'Unknown resource {resource!r}',
                    'available': RESOURCES}
        params = dict(args.get('params') or {})
        if args.get('page'):
            params['page'] = args['page']
        if args.get('per_page'):
            params['per_page'] = args['per_page']
        return api_get(f'/api/v1/{resource}', params)
    if name == 'rotk_get':
        resource = args['resource']
        if resource not in RESOURCES:
            return {'error': f'Unknown resource {resource!r}',
                    'available': RESOURCES}
        return api_get(f'/api/v1/{resource}/{int(args["id"])}')
    if name == 'rotk_find_data_gaps':
        return find_data_gaps(args['check'])
    if name == 'rotk_fetch':
        path = args['path']
        if not path.startswith('/api/v1'):
            return {'error': "Only '/api/v1...' paths are allowed."}
        return api_get(path)
    raise KeyError(name)


# ---------------------------------------------------------------------------
# JSON-RPC / MCP plumbing
# ---------------------------------------------------------------------------

def handle_message(msg):
    """One JSON-RPC message in → response dict out (None for
    notifications / messages that need no reply)."""
    method = msg.get('method')
    msg_id = msg.get('id')
    is_notification = 'id' not in msg

    def result(payload):
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': payload}

    def error(code, message):
        return {'jsonrpc': '2.0', 'id': msg_id,
                'error': {'code': code, 'message': message}}

    if method == 'initialize':
        client_version = (msg.get('params') or {}).get(
            'protocolVersion', DEFAULT_PROTOCOL_VERSION)
        return result({
            'protocolVersion': client_version,
            'capabilities': {'tools': {}},
            'serverInfo': SERVER_INFO,
        })
    if method in ('notifications/initialized', 'initialized'):
        return None
    if method == 'ping':
        return result({})
    if method == 'tools/list':
        return result({'tools': TOOLS})
    if method == 'tools/call':
        params = msg.get('params') or {}
        name = params.get('name', '')
        args = params.get('arguments') or {}
        try:
            payload = call_tool(name, args)
            return result({
                'content': [{'type': 'text',
                             'text': json.dumps(payload, indent=2,
                                                ensure_ascii=False)}],
                'isError': False,
            })
        except KeyError:
            return result({
                'content': [{'type': 'text',
                             'text': f'Unknown tool: {name}'}],
                'isError': True,
            })
        except Exception as exc:   # requests errors, bad args, ...
            return result({
                'content': [{'type': 'text',
                             'text': f'Tool {name} failed: {exc}'}],
                'isError': True,
            })
    if is_notification:
        return None
    return error(-32601, f'Method not found: {method}')


def serve():
    log(f'serving; API base = {API_BASE}')
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            print(json.dumps({'jsonrpc': '2.0', 'id': None,
                              'error': {'code': -32700,
                                        'message': 'Parse error'}}),
                  flush=True)
            continue
        response = handle_message(msg)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    log('stdin closed — exiting')


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def selftest():
    """Offline protocol sanity: handshake + tools/list shapes."""
    init = handle_message({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                           'params': {'protocolVersion': '2025-06-18'}})
    assert init['result']['protocolVersion'] == '2025-06-18'
    assert 'tools' in init['result']['capabilities']
    assert handle_message({'jsonrpc': '2.0',
                           'method': 'notifications/initialized'}) is None
    tools = handle_message({'jsonrpc': '2.0', 'id': 2,
                            'method': 'tools/list'})
    names = [t['name'] for t in tools['result']['tools']]
    assert names == ['rotk_api_index', 'rotk_list', 'rotk_get',
                     'rotk_find_data_gaps', 'rotk_fetch'], names
    for t in tools['result']['tools']:
        assert t['inputSchema']['type'] == 'object'
    bad = handle_message({'jsonrpc': '2.0', 'id': 3, 'method': 'nope'})
    assert bad['error']['code'] == -32601
    guard = handle_message({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                            'params': {'name': 'rotk_fetch',
                                       'arguments': {'path': '/admin'}}})
    assert 'Only' in guard['result']['content'][0]['text']
    print('selftest OK — 5 tools, handshake + guards behave')


def smoke():
    data = api_get('/api/v1/')
    endpoints = data.get('endpoints') or []
    print(f'{API_BASE}/api/v1/ → {len(endpoints)} endpoints '
          f'({data.get("name", "?")} {data.get("version", "?")})')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    elif '--smoke' in sys.argv:
        smoke()
    else:
        serve()
