"""Endpoint catalogue — the single source of truth for what the API
serves and which query params each list endpoint accepts.

Consumed by:
  1. GET /api/v1/          — the self-describing index (MCP-friendly)
  2. /admin/api-explorer   — generates the param form per endpoint

Param `type` values the explorer understands:
  'text' | 'number' | 'select' (requires `choices`)

Every list endpoint implicitly accepts `page` and `per_page` — the
explorer adds those two fields automatically, so they're not repeated
in each entry here.
"""

ENDPOINTS = [
    {
        'key': 'characters',
        'title': 'Characters',
        'path': '/api/v1/characters',
        'detail_path': '/api/v1/characters/<id>',
        'description': (
            'Characters with factions, roles, relationships, portraits, '
            'external links and chapter appearances joined in.'
        ),
        'params': [
            {'name': 'q', 'type': 'text',
             'label': 'Search (name / courtesy / alias contains)'},
            {'name': 'letter', 'type': 'text',
             'label': 'Name starts with (single letter)'},
            {'name': 'faction_id', 'type': 'number',
             'label': 'Member of faction id (past or present)'},
            {'name': 'primary_faction_id', 'type': 'number',
             'label': 'Primary faction id'},
            {'name': 'role_id', 'type': 'number', 'label': 'Role id'},
            {'name': 'sort', 'type': 'select', 'label': 'Sort by',
             'choices': ['name', 'mentions']},
            {'name': 'dir', 'type': 'select', 'label': 'Sort direction',
             'choices': ['asc', 'desc']},
        ],
    },
    {
        'key': 'factions',
        'title': 'Factions',
        'path': '/api/v1/factions',
        'detail_path': '/api/v1/factions/<id>',
        'description': ('Factions with colours, leaders and member counts; '
                        'detail adds members, links and territory-map years.'),
        'params': [
            {'name': 'q', 'type': 'text', 'label': 'Search (name contains)'},
        ],
    },
    {
        'key': 'roles',
        'title': 'Roles',
        'path': '/api/v1/roles',
        'detail_path': '/api/v1/roles/<id>',
        'description': 'Character roles; detail adds the characters holding each.',
        'params': [
            {'name': 'q', 'type': 'text', 'label': 'Search (name contains)'},
        ],
    },
    {
        'key': 'tags',
        'title': 'Tags',
        'path': '/api/v1/tags',
        'detail_path': '/api/v1/tags/<id>',
        'description': 'Image/portrait tags with usage counts.',
        'params': [
            {'name': 'q', 'type': 'text', 'label': 'Search (name contains)'},
        ],
    },
    {
        'key': 'events',
        'title': 'Events',
        'path': '/api/v1/events',
        'detail_path': '/api/v1/events/<id>',
        'description': ('Events with type, parsed year span, location, sided '
                        'faction participation and chapter appearances.'),
        'params': [
            {'name': 'q', 'type': 'text',
             'label': 'Search (name / alias contains)'},
            {'name': 'location_id', 'type': 'number', 'label': 'Location id'},
            {'name': 'event_type_id', 'type': 'number',
             'label': 'Event type id'},
            {'name': 'chapter_num', 'type': 'number',
             'label': 'Appears in chapter number'},
        ],
    },
    {
        'key': 'event-types',
        'title': 'Event Types',
        'path': '/api/v1/event-types',
        'detail_path': '/api/v1/event-types/<id>',
        'description': 'Event categories incl. the two faction-list labels.',
        'params': [
            {'name': 'q', 'type': 'text', 'label': 'Search (name contains)'},
        ],
    },
    {
        'key': 'locations',
        'title': 'Locations',
        'path': '/api/v1/locations',
        'detail_path': '/api/v1/locations/<id>',
        'description': ('Locations with type, ancestry chain and coordinates; '
                        'detail adds GeoJSON, children, events and chapters.'),
        'params': [
            {'name': 'q', 'type': 'text',
             'label': 'Search (name / alias contains)'},
            {'name': 'location_type_id', 'type': 'number',
             'label': 'Location type id'},
            {'name': 'parent_id', 'type': 'number',
             'label': 'Direct parent location id'},
        ],
    },
    {
        'key': 'location-types',
        'title': 'Location Types',
        'path': '/api/v1/location-types',
        'detail_path': '/api/v1/location-types/<id>',
        'description': 'Location categories (Province, Commandery, …).',
        'params': [
            {'name': 'q', 'type': 'text', 'label': 'Search (name contains)'},
        ],
    },
    {
        'key': 'chapters',
        'title': 'Chapters',
        'path': '/api/v1/chapters',
        'detail_path': '/api/v1/chapters/<chapter_num>',
        'description': ('Chapters incl. FULL prose content, parsed years and '
                        'associated characters / events / locations. Detail '
                        'is addressed by chapter number. Default page size '
                        'is small because content rides along.'),
        'params': [
            {'name': 'q', 'type': 'text', 'label': 'Search (title contains)'},
            {'name': 'character_id', 'type': 'number',
             'label': 'Features character id'},
            {'name': 'event_id', 'type': 'number', 'label': 'Features event id'},
            {'name': 'location_id', 'type': 'number',
             'label': 'Features location id'},
        ],
    },
    {
        'key': 'relationships',
        'title': 'Relationships',
        'path': '/api/v1/relationships',
        'detail_path': None,
        'description': ('Family ties between characters, with both ends\' '
                        'sex-resolved labels.'),
        'params': [
            {'name': 'character_id', 'type': 'number',
             'label': 'Involving character id'},
            {'name': 'relationship_type_id', 'type': 'number',
             'label': 'Relationship type id'},
        ],
    },
    {
        'key': 'relationship-types',
        'title': 'Relationship Types',
        'path': '/api/v1/relationship-types',
        'detail_path': '/api/v1/relationship-types/<id>',
        'description': 'Tie types with per-end (and per-sex) labels.',
        'params': [
            {'name': 'q', 'type': 'text', 'label': 'Search (name contains)'},
        ],
    },
    {
        'key': 'year-maps',
        'title': 'Year Maps',
        'path': '/api/v1/year-maps',
        'detail_path': '/api/v1/year-maps/<year>',
        'description': ('Per-year territory map images with attribution and '
                        'the factions present that year (incl. leaders). '
                        'Detail is addressed by year.'),
        'params': [
            {'name': 'year_from', 'type': 'number', 'label': 'Year from'},
            {'name': 'year_to', 'type': 'number', 'label': 'Year to'},
        ],
    },
    {
        'key': 'annotations',
        'title': 'Annotations (public)',
        'path': '/api/v1/annotations',
        'detail_path': None,
        'description': ('PUBLIC reader annotations only — thread entries '
                        'with chapter refs and a content-addressed '
                        'thread_key for grouping. Private admin threads '
                        'are never served.'),
        'params': [
            {'name': 'chapter_num', 'type': 'number',
             'label': 'Chapter number'},
        ],
    },
]
