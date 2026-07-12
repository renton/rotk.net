"""Public read-only JSON API routes (GET only, mounted at /api/v1).

Conventions:
  - Lists return the envelope {items, page, per_page, pages, total};
    detail endpoints return the bare object.
  - Errors return {"error": "..."} with the status code (the blueprint-
    scoped handlers below keep even 404s JSON).
  - Everything is public — but ONLY public data is served: queries
    filter soft-deleted / hidden rows, and there are deliberately no
    users / edits / private-annotation endpoints.
"""
from flask import jsonify, request, url_for

from app import db
from . import api
from .registry import ENDPOINTS

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 100


@api.before_request
def _enforce_read_only():
    """Belt-and-braces: the API is READ-ONLY. Every route below is
    GET-only already, but this guard makes the property structural —
    a future route accidentally declaring methods=['POST'] still gets
    refused here."""
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        return jsonify(error='Method not allowed — this API is read-only.'), 405


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def int_arg(name, default=None):
    """request.args int parse — None when absent, 400 when malformed."""
    raw = request.args.get(name)
    if raw is None or raw == '':
        return default
    try:
        return int(raw)
    except ValueError:
        from flask import abort
        abort(400, description=f"Query param {name!r} must be an integer.")


def paginate(query, serialize, default_per_page=DEFAULT_PER_PAGE):
    """Run the standard list envelope over a query.

    `serialize` is called per item. per_page is capped so a caller can't
    ask for the whole table in one shot."""
    page = int_arg('page', 1) or 1
    per_page = int_arg('per_page', default_per_page) or default_per_page
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    pagination = query.paginate(page=max(1, page), per_page=per_page,
                                error_out=False)
    return jsonify({
        'items': [serialize(obj) for obj in pagination.items],
        'page': pagination.page,
        'per_page': per_page,
        'pages': pagination.pages,
        'total': pagination.total,
    })


def like_filter(query, column, raw):
    """Case-insensitive contains filter, skipped when the term is blank."""
    term = (raw or '').strip()
    if term:
        return query.filter(column.ilike(f'%{term}%'))
    return query


# --------------------------------------------------------------------------
# JSON error handlers — keep every API error a JSON body, including the
# default HTML abort pages Flask would otherwise emit.
# --------------------------------------------------------------------------

@api.errorhandler(400)
def _bad_request(err):
    return jsonify(error=getattr(err, 'description', 'Bad request.')), 400


@api.errorhandler(404)
def _not_found(err):
    return jsonify(error='Not found.'), 404


@api.errorhandler(429)
def _rate_limited(err):
    return jsonify(error='Rate limit exceeded — slow down.'), 429


@api.errorhandler(405)
def _method_not_allowed(err):
    return jsonify(error='Method not allowed — this API is read-only.'), 405


# --------------------------------------------------------------------------
# Index — self-describing endpoint catalogue (MCP-friendly)
# --------------------------------------------------------------------------

@api.route('/', methods=['GET'])
def index():
    return jsonify({
        'name': 'rotk.net API',
        'version': 'v1',
        'description': (
            'Read-only public data of the annotated Romance of the Three '
            'Kingdoms edition at rotk.net. Lists are paginated with '
            '?page/?per_page and return {items, page, per_page, pages, '
            'total}.'
        ),
        'endpoints': ENDPOINTS,
    })


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------

from sqlalchemy.orm import selectinload  # noqa: E402

from app.models import (  # noqa: E402
    Annotation, Chapter, Character, Event, EventType, Faction, Location,
    LocationType, Relationship, RelationshipType, Role, Tag, TagAssociation,
    Url, YearMap,
)
from . import serializers as ser  # noqa: E402


def envelope(pagination, per_page, items):
    return jsonify({
        'items': items,
        'page': pagination.page,
        'per_page': per_page,
        'pages': pagination.pages,
        'total': pagination.total,
    })


def get_pagination(query, default_per_page=DEFAULT_PER_PAGE):
    page = int_arg('page', 1) or 1
    per_page = int_arg('per_page', default_per_page) or default_per_page
    per_page = max(1, min(per_page, MAX_PER_PAGE))
    return query.paginate(page=max(1, page), per_page=per_page,
                          error_out=False), per_page


def _urls_map(target_type, ids):
    """{target_id: [url_entry, ...]} for one polymorphic owner type."""
    out = {}
    if not ids:
        return out
    rows = (
        Url.query
        .filter(Url.is_deleted.is_(False),
                Url.target_type == target_type,
                Url.target_id.in_(ids))
        .options(selectinload(Url.url_type))
        .order_by(Url.name)
        .all()
    )
    for u in rows:
        out.setdefault(u.target_id, []).append(ser.url_entry(u))
    return out


def _relationships_map(char_ids):
    """{character_id: [{character, label, type}, ...]} resolved from each
    character's side of every tie touching them."""
    out = {}
    if not char_ids:
        return out
    rows = (
        Relationship.query
        .filter((Relationship.character1_id.in_(char_ids))
                | (Relationship.character2_id.in_(char_ids)))
        .options(
            selectinload(Relationship.character1),
            selectinload(Relationship.character2),
            selectinload(Relationship.relationship_type),
        )
        .all()
    )
    for r in rows:
        for cid in (r.character1_id, r.character2_id):
            if cid not in char_ids:
                continue
            other, label = r.describe_for(cid)
            if other.is_deleted or other.id == cid:
                continue
            out.setdefault(cid, []).append({
                'relationship_id': r.id,
                'character': ser.character_ref(other),
                'label': label,
                'type': {'id': r.relationship_type_id,
                         'name': r.relationship_type.name},
            })
    for entries in out.values():
        entries.sort(key=lambda d: (d['label'], d['character']['name']))
    return out


def _characters_json(items):
    """Serialize characters with all joins, bulk-loading every hop so a
    50-row page costs a fixed handful of queries (the roles / factions
    relationships are lazy='dynamic' — per-row access would N+1)."""
    ids = {c.id for c in items}

    def m2m_tag_map(assoc_table, model, fk_col):
        out = {}
        if not ids:
            return out
        rows = (
            db.session.query(assoc_table.c.character_id, model)
            .join(model, model.id == fk_col)
            .filter(assoc_table.c.character_id.in_(ids))
            .order_by(model.name)
            .all()
        )
        for cid, tag in rows:
            if getattr(tag, 'is_hidden', False):
                continue
            out.setdefault(cid, []).append(ser.tag_shaped_ref(tag))
        return out

    factions_map = m2m_tag_map(Character.faction_table, Faction,
                               Character.faction_table.c.faction_id)
    roles_map = m2m_tag_map(Character.role_table, Role,
                            Character.role_table.c.role_id)
    rel_map = _relationships_map(ids)
    urls_map = _urls_map('character', ids)

    chapters_map = {}
    if ids:
        ch_rows = (
            db.session.query(
                Character.chapter_character.c.character_id,
                Chapter.chapter_num,
                Chapter.name,
                Character.chapter_character.c.keywords,
                Character.chapter_character.c.summary,
            )
            .join(Chapter,
                  Chapter.id == Character.chapter_character.c.chapter_id)
            .filter(Character.chapter_character.c.character_id.in_(ids))
            .order_by(Chapter.chapter_num)
            .all()
        )
        for cid, num, name, keywords, summary in ch_rows:
            chapters_map.setdefault(cid, []).append({
                'chapter_num': num,
                'title': name or '',
                'keywords': keywords or '',
                'summary': summary or '',
            })

    out = []
    for c in items:
        payload = ser.character_ref(c)
        payload.update({
            'courtesy_name': c.courtesty_name or '',
            'chinese_courtesy_name': c.chinese_courtesty_name or '',
            'aliases': [a.strip() for a in (c.aliases or '').split(',')
                        if a.strip()],
            'birth': ser.date_span(c.birth_date),
            'death': ser.date_span(c.death_date),
            'ancestral_home': c.ancestral_home or '',
            'book_mention_count': c.book_mention_count or 0,
            'primary_faction': ser.faction_ref(c.primary_faction),
            'factions': factions_map.get(c.id, []),
            'roles': roles_map.get(c.id, []),
            'relationships': rel_map.get(c.id, []),
            'portraits': ser.visible_portraits(c),
            'urls': urls_map.get(c.id, []),
            'chapters': chapters_map.get(c.id, []),
        })
        out.append(payload)
    return out


@api.route('/characters', methods=['GET'])
def characters():
    query = (
        Character.query
        .filter(Character.is_deleted.is_(False))
        .options(selectinload(Character.portraits),
                 selectinload(Character.primary_faction))
    )
    q = (request.args.get('q') or '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(
            Character.name.ilike(like)
            | Character.courtesty_name.ilike(like)
            | Character.aliases.ilike(like)
        )
    letter = (request.args.get('letter') or '').strip()
    if letter:
        query = query.filter(Character.name.startswith(letter[0].upper()))
    faction_id = int_arg('faction_id')
    if faction_id is not None:
        query = query.filter(Character.factions.any(Faction.id == faction_id))
    primary_faction_id = int_arg('primary_faction_id')
    if primary_faction_id is not None:
        query = query.filter(
            Character.primary_faction_id == primary_faction_id)
    role_id = int_arg('role_id')
    if role_id is not None:
        query = query.filter(Character.roles.any(Role.id == role_id))

    direction = request.args.get('dir', 'asc')
    if request.args.get('sort') == 'mentions':
        col = Character.book_mention_count
        order = col.asc() if direction == 'asc' else col.desc()
        query = query.order_by(order, Character.name)
    else:
        query = query.order_by(
            Character.name.desc() if direction == 'desc'
            else Character.name.asc())

    pagination, per_page = get_pagination(query)
    return envelope(pagination, per_page, _characters_json(pagination.items))


@api.route('/characters/<int:character_id>', methods=['GET'])
def character_detail(character_id):
    c = (
        Character.query
        .filter(Character.id == character_id,
                Character.is_deleted.is_(False))
        .options(selectinload(Character.portraits),
                 selectinload(Character.primary_faction))
        .first_or_404()
    )
    return jsonify(_characters_json([c])[0])


# --------------------------------------------------------------------------
# Factions / Roles / Tags
# --------------------------------------------------------------------------

from sqlalchemy import func  # noqa: E402


def _tag_shaped_query(model):
    """Base list query for AbstractTag rows: active, visible, by name,
    with the standard q filter applied."""
    query = model.query.filter(model.is_deleted.is_(False),
                               model.is_hidden.is_(False))
    query = like_filter(query, model.name, request.args.get('q'))
    return query.order_by(model.name)


def _faction_json(f, member_counts=None, members=False):
    payload = ser.tag_shaped_ref(f)
    payload['leaders'] = [ser.character_ref(c) for c in f.leaders
                          if not c.is_deleted]
    if member_counts is not None:
        payload['member_count'] = member_counts.get(f.id, 0)
    if members:
        member_rows = (
            db.session.query(Character)
            .join(Character.faction_table,
                  Character.faction_table.c.character_id == Character.id)
            .filter(Character.faction_table.c.faction_id == f.id,
                    Character.is_deleted.is_(False))
            .order_by(Character.name)
            .all()
        )
        payload['member_count'] = len(member_rows)
        payload['members'] = [ser.character_ref(c) for c in member_rows]
        payload['urls'] = ser.urls_for(f)
        payload['year_map_years'] = [
            y for (y,) in
            db.session.query(YearMap.year)
            .join(YearMap.faction_table,
                  YearMap.faction_table.c.year_map_id == YearMap.id)
            .filter(YearMap.faction_table.c.faction_id == f.id)
            .order_by(YearMap.year)
            .all()
        ]
    return payload


def _member_counts(faction_ids):
    if not faction_ids:
        return {}
    rows = (
        db.session.query(
            Character.faction_table.c.faction_id,
            func.count(Character.faction_table.c.character_id),
        )
        .join(Character,
              Character.id == Character.faction_table.c.character_id)
        .filter(Character.faction_table.c.faction_id.in_(faction_ids),
                Character.is_deleted.is_(False))
        .group_by(Character.faction_table.c.faction_id)
        .all()
    )
    return dict(rows)


@api.route('/factions', methods=['GET'])
def factions():
    query = _tag_shaped_query(Faction).options(selectinload(Faction.leaders))
    pagination, per_page = get_pagination(query)
    counts = _member_counts([f.id for f in pagination.items])
    return envelope(pagination, per_page,
                    [_faction_json(f, member_counts=counts)
                     for f in pagination.items])


@api.route('/factions/<int:faction_id>', methods=['GET'])
def faction_detail(faction_id):
    f = (
        Faction.query
        .filter(Faction.id == faction_id,
                Faction.is_deleted.is_(False),
                Faction.is_hidden.is_(False))
        .options(selectinload(Faction.leaders))
        .first_or_404()
    )
    return jsonify(_faction_json(f, members=True))


def _characters_count_map(assoc_table, id_col, ids):
    """{tag_id: active-character count} over a character M2M table."""
    if not ids:
        return {}
    rows = (
        db.session.query(id_col, func.count(assoc_table.c.character_id))
        .join(Character, Character.id == assoc_table.c.character_id)
        .filter(id_col.in_(ids), Character.is_deleted.is_(False))
        .group_by(id_col)
        .all()
    )
    return dict(rows)


@api.route('/roles', methods=['GET'])
def roles():
    query = _tag_shaped_query(Role)
    pagination, per_page = get_pagination(query)
    counts = _characters_count_map(
        Character.role_table, Character.role_table.c.role_id,
        [r.id for r in pagination.items])
    items = []
    for r in pagination.items:
        payload = ser.tag_shaped_ref(r)
        payload['character_count'] = counts.get(r.id, 0)
        items.append(payload)
    return envelope(pagination, per_page, items)


@api.route('/roles/<int:role_id>', methods=['GET'])
def role_detail(role_id):
    r = (
        Role.query
        .filter(Role.id == role_id, Role.is_deleted.is_(False),
                Role.is_hidden.is_(False))
        .first_or_404()
    )
    payload = ser.tag_shaped_ref(r)
    chars = (
        db.session.query(Character)
        .join(Character.role_table,
              Character.role_table.c.character_id == Character.id)
        .filter(Character.role_table.c.role_id == r.id,
                Character.is_deleted.is_(False))
        .order_by(Character.name)
        .all()
    )
    payload['character_count'] = len(chars)
    payload['characters'] = [ser.character_ref(c) for c in chars]
    payload['urls'] = ser.urls_for(r)
    return jsonify(payload)


@api.route('/tags', methods=['GET'])
def tags():
    query = _tag_shaped_query(Tag)
    pagination, per_page = get_pagination(query)
    ids = [t.id for t in pagination.items]
    counts = {}
    if ids:
        counts = dict(
            db.session.query(TagAssociation.tag_id,
                             func.count(TagAssociation.id))
            .filter(TagAssociation.tag_id.in_(ids))
            .group_by(TagAssociation.tag_id)
            .all()
        )
    items = []
    for t in pagination.items:
        payload = ser.tag_shaped_ref(t)
        payload['usage_count'] = counts.get(t.id, 0)
        items.append(payload)
    return envelope(pagination, per_page, items)


@api.route('/tags/<int:tag_id>', methods=['GET'])
def tag_detail(tag_id):
    t = (
        Tag.query
        .filter(Tag.id == tag_id, Tag.is_deleted.is_(False),
                Tag.is_hidden.is_(False))
        .first_or_404()
    )
    payload = ser.tag_shaped_ref(t)
    payload['usage_count'] = t.associations.count()
    return jsonify(payload)


# --------------------------------------------------------------------------
# Events / Event Types
# --------------------------------------------------------------------------

from app.models.event import event_chapter  # noqa: E402


def _events_json(items):
    ids = {e.id for e in items}
    urls_map = _urls_map('event', ids)

    chapters_map = {}
    if ids:
        rows = (
            db.session.query(
                event_chapter.c.event_id,
                Chapter.chapter_num,
                Chapter.name,
                event_chapter.c.keywords,
            )
            .join(Chapter, Chapter.id == event_chapter.c.chapter_id)
            .filter(event_chapter.c.event_id.in_(ids))
            .order_by(Chapter.chapter_num)
            .all()
        )
        for eid, num, name, keywords in rows:
            chapters_map.setdefault(eid, []).append({
                'chapter_num': num,
                'title': name or '',
                'keywords': keywords or '',
            })

    out = []
    for e in items:
        et = e.event_type
        out.append({
            'id': e.id,
            'name': e.name,
            'chinese_name': e.chinese_name or '',
            'aliases': [a.strip() for a in (e.aliases or '').split(',')
                        if a.strip()],
            'date': ser.date_span(e.date),
            'event_type': ser.event_type_ref(et),
            'location': ser.location_ref(e.location),
            'geo_point_override': e.geo_point_override or '',
            'hide_on_map': bool(e.hide_on_map),
            'factions1': {
                'label': (et.factions1_label if et and et.factions1_label
                          else 'Factions'),
                'factions': [ser.faction_ref(f) for f in e.factions1
                             if not f.is_hidden],
            },
            'factions2': {
                'label': (et.factions2_label if et and et.factions2_label
                          else 'Factions'),
                'factions': [ser.faction_ref(f) for f in e.factions2
                             if not f.is_hidden],
            },
            'urls': urls_map.get(e.id, []),
            'chapters': chapters_map.get(e.id, []),
        })
    return out


def _event_base_query():
    return (
        Event.query
        .filter(Event.is_deleted.is_(False))
        .options(
            selectinload(Event.event_type),
            selectinload(Event.location).selectinload(Location.location_type),
            selectinload(Event.factions1),
            selectinload(Event.factions2),
        )
    )


@api.route('/events', methods=['GET'])
def events():
    query = _event_base_query()
    q = (request.args.get('q') or '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(Event.name.ilike(like)
                             | Event.aliases.ilike(like))
    location_id = int_arg('location_id')
    if location_id is not None:
        query = query.filter(Event.location_id == location_id)
    event_type_id = int_arg('event_type_id')
    if event_type_id is not None:
        query = query.filter(Event.event_type_id == event_type_id)
    chapter_num = int_arg('chapter_num')
    if chapter_num is not None:
        query = (
            query.join(event_chapter, event_chapter.c.event_id == Event.id)
            .join(Chapter, Chapter.id == event_chapter.c.chapter_id)
            .filter(Chapter.chapter_num == chapter_num)
        )
    query = query.order_by(Event.name)
    pagination, per_page = get_pagination(query)
    return envelope(pagination, per_page, _events_json(pagination.items))


@api.route('/events/<int:event_id>', methods=['GET'])
def event_detail(event_id):
    e = (
        _event_base_query()
        .filter(Event.id == event_id)
        .first_or_404()
    )
    return jsonify(_events_json([e])[0])


@api.route('/event-types', methods=['GET'])
def event_types():
    query = _tag_shaped_query(EventType)
    pagination, per_page = get_pagination(query)
    ids = [t.id for t in pagination.items]
    counts = {}
    if ids:
        counts = dict(
            db.session.query(Event.event_type_id, func.count(Event.id))
            .filter(Event.event_type_id.in_(ids),
                    Event.is_deleted.is_(False))
            .group_by(Event.event_type_id)
            .all()
        )
    items = []
    for t in pagination.items:
        payload = ser.event_type_ref(t)
        payload['event_count'] = counts.get(t.id, 0)
        items.append(payload)
    return envelope(pagination, per_page, items)


@api.route('/event-types/<int:type_id>', methods=['GET'])
def event_type_detail(type_id):
    t = (
        EventType.query
        .filter(EventType.id == type_id, EventType.is_deleted.is_(False),
                EventType.is_hidden.is_(False))
        .first_or_404()
    )
    payload = ser.event_type_ref(t)
    payload['event_count'] = Event.query.filter_by(
        event_type_id=t.id, is_deleted=False).count()
    return jsonify(payload)


# --------------------------------------------------------------------------
# Locations / Location Types
# --------------------------------------------------------------------------

from app.models.location import chapter_location  # noqa: E402


def _ancestry_chains(items):
    """{location_id: [ref, ...]} root→leaf ancestry per location.

    Bulk: iteratively load each missing tier of parents by id (chains
    are ≤ ~4 deep) instead of lazy-walking per row. Cycle-guarded like
    the sidebar walk."""
    by_id = {loc.id: loc for loc in items}
    frontier = {loc.parent_id for loc in items
                if loc.parent_id and loc.parent_id not in by_id}
    depth = 0
    while frontier and depth < 10:
        rows = Location.query.filter(Location.id.in_(frontier)).all()
        for loc in rows:
            by_id[loc.id] = loc
        frontier = {loc.parent_id for loc in rows
                    if loc.parent_id and loc.parent_id not in by_id}
        depth += 1

    chains = {}
    for loc in items:
        chain = []
        seen = {loc.id}
        cur = by_id.get(loc.parent_id) if loc.parent_id else None
        steps = 0
        while cur is not None and cur.id not in seen and steps < 10:
            chain.append(ser.location_ref(cur))
            seen.add(cur.id)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
            steps += 1
        chain.reverse()   # root → leaf reading order
        chains[loc.id] = chain
    return chains


def _locations_json(items, detail=False):
    ids = {loc.id for loc in items}
    chains = _ancestry_chains(items)

    out = []
    for loc in items:
        payload = ser.location_ref(loc)
        payload.update({
            'aliases': [a.strip() for a in (loc.aliases or '').split(',')
                        if a.strip()],
            'parent': ser.location_ref(loc.parent) if loc.parent_id else None,
            'ancestry': chains.get(loc.id, []),
            'latitude': loc.latitude,
            'longitude': loc.longitude,
            'has_geojson': bool(loc.geojson),
        })
        out.append(payload)

    if detail:
        # Single-item extras — full geometry + children/events/chapters.
        loc, payload = items[0], out[0]
        payload['geojson'] = loc.geojson if loc.geojson else None
        payload['children'] = [
            ser.location_ref(child)
            for child in sorted(
                (c for c in loc.children if not c.is_deleted),
                key=lambda c: c.name)
        ]
        payload['events_here'] = [
            {'id': e.id, 'name': e.name}
            for e in Event.query
            .filter(Event.location_id == loc.id,
                    Event.is_deleted.is_(False))
            .order_by(Event.name).all()
        ]
        payload['chapters'] = [
            {'chapter_num': num, 'title': name or '', 'keywords': kw or ''}
            for num, name, kw in
            db.session.query(Chapter.chapter_num, Chapter.name,
                             chapter_location.c.keywords)
            .join(chapter_location,
                  chapter_location.c.chapter_id == Chapter.id)
            .filter(chapter_location.c.location_id == loc.id)
            .order_by(Chapter.chapter_num)
            .all()
        ]
        payload['urls'] = ser.urls_for(loc)
    return out


def _location_base_query():
    return (
        Location.query
        .filter(Location.is_deleted.is_(False))
        .options(selectinload(Location.location_type))
    )


@api.route('/locations', methods=['GET'])
def locations():
    query = _location_base_query()
    q = (request.args.get('q') or '').strip()
    if q:
        like = f'%{q}%'
        query = query.filter(Location.name.ilike(like)
                             | Location.aliases.ilike(like))
    location_type_id = int_arg('location_type_id')
    if location_type_id is not None:
        query = query.filter(Location.location_type_id == location_type_id)
    parent_id = int_arg('parent_id')
    if parent_id is not None:
        query = query.filter(Location.parent_id == parent_id)
    query = query.order_by(Location.name)
    pagination, per_page = get_pagination(query)
    return envelope(pagination, per_page, _locations_json(pagination.items))


@api.route('/locations/<int:location_id>', methods=['GET'])
def location_detail(location_id):
    loc = (
        _location_base_query()
        .filter(Location.id == location_id)
        .first_or_404()
    )
    return jsonify(_locations_json([loc], detail=True)[0])


@api.route('/location-types', methods=['GET'])
def location_types():
    query = _tag_shaped_query(LocationType)
    pagination, per_page = get_pagination(query)
    ids = [t.id for t in pagination.items]
    counts = {}
    if ids:
        counts = dict(
            db.session.query(Location.location_type_id,
                             func.count(Location.id))
            .filter(Location.location_type_id.in_(ids),
                    Location.is_deleted.is_(False))
            .group_by(Location.location_type_id)
            .all()
        )
    items = []
    for t in pagination.items:
        payload = ser.tag_shaped_ref(t)
        payload['point_type'] = t.point_type
        payload['location_count'] = counts.get(t.id, 0)
        items.append(payload)
    return envelope(pagination, per_page, items)


@api.route('/location-types/<int:type_id>', methods=['GET'])
def location_type_detail(type_id):
    t = (
        LocationType.query
        .filter(LocationType.id == type_id,
                LocationType.is_deleted.is_(False),
                LocationType.is_hidden.is_(False))
        .first_or_404()
    )
    payload = ser.tag_shaped_ref(t)
    payload['point_type'] = t.point_type
    payload['location_count'] = Location.query.filter_by(
        location_type_id=t.id, is_deleted=False).count()
    return jsonify(payload)


# --------------------------------------------------------------------------
# Chapters — full prose everywhere (per user decision), so the default
# page size stays small.
# --------------------------------------------------------------------------

import re as _re  # noqa: E402

from app.blueprints.main.views import _chapter_years  # noqa: E402

CHAPTERS_PER_PAGE = 20
_BR_RE = _re.compile(r'<\s*br\s*/?\s*>', _re.IGNORECASE)


def _chapters_json(items):
    ids = {c.id for c in items}

    chars_map, events_map, locs_map, ann_counts = {}, {}, {}, {}
    if ids:
        for chid, character, kw, summary in (
            db.session.query(
                Character.chapter_character.c.chapter_id,
                Character,
                Character.chapter_character.c.keywords,
                Character.chapter_character.c.summary,
            )
            .join(Character,
                  Character.id == Character.chapter_character.c.character_id)
            .filter(Character.chapter_character.c.chapter_id.in_(ids),
                    Character.is_deleted.is_(False))
            .order_by(Character.name)
            .all()
        ):
            entry = ser.character_ref(character)
            entry['keywords'] = kw or ''
            entry['summary'] = summary or ''
            chars_map.setdefault(chid, []).append(entry)

        for chid, event, kw in (
            db.session.query(event_chapter.c.chapter_id, Event,
                             event_chapter.c.keywords)
            .join(Event, Event.id == event_chapter.c.event_id)
            .filter(event_chapter.c.chapter_id.in_(ids),
                    Event.is_deleted.is_(False))
            .order_by(Event.name)
            .all()
        ):
            events_map.setdefault(chid, []).append(
                {'id': event.id, 'name': event.name, 'keywords': kw or ''})

        for chid, location, kw in (
            db.session.query(chapter_location.c.chapter_id, Location,
                             chapter_location.c.keywords)
            .join(Location, Location.id == chapter_location.c.location_id)
            .filter(chapter_location.c.chapter_id.in_(ids),
                    Location.is_deleted.is_(False))
            .order_by(Location.name)
            .all()
        ):
            entry = ser.location_ref(location)
            entry['keywords'] = kw or ''
            locs_map.setdefault(chid, []).append(entry)

        ann_counts = dict(
            db.session.query(Annotation.chapter_id,
                             func.count(Annotation.id))
            .filter(Annotation.chapter_id.in_(ids),
                    Annotation.is_public.is_(True),
                    Annotation.is_deleted.is_(False))
            .group_by(Annotation.chapter_id)
            .all()
        )

    # prev/next resolved against the full ordered chapter-number list.
    all_nums = [n for (n,) in
                db.session.query(Chapter.chapter_num)
                .filter(Chapter.is_deleted.is_(False))
                .order_by(Chapter.chapter_num).all()]
    pos = {n: i for i, n in enumerate(all_nums)}

    out = []
    for c in items:
        i = pos.get(c.chapter_num)
        out.append({
            'chapter_num': c.chapter_num,
            'title': _BR_RE.sub(' ', c.name or '').strip(),
            'date': ser.date_span(c.date),
            'years': _chapter_years(c.date),
            'content': c.content or '',
            'characters': chars_map.get(c.id, []),
            'events': events_map.get(c.id, []),
            'locations': locs_map.get(c.id, []),
            'public_annotation_count': ann_counts.get(c.id, 0),
            'prev_chapter_num': (all_nums[i - 1]
                                 if i is not None and i > 0 else None),
            'next_chapter_num': (all_nums[i + 1]
                                 if i is not None and i + 1 < len(all_nums)
                                 else None),
        })
    return out


@api.route('/chapters', methods=['GET'])
def chapters():
    query = Chapter.query.filter(Chapter.is_deleted.is_(False))
    query = like_filter(query, Chapter.name, request.args.get('q'))
    character_id = int_arg('character_id')
    if character_id is not None:
        query = query.filter(
            Chapter.characters.any(Character.id == character_id))
    event_id = int_arg('event_id')
    if event_id is not None:
        query = query.filter(Chapter.events.any(Event.id == event_id))
    location_id = int_arg('location_id')
    if location_id is not None:
        query = query.filter(
            Chapter.locations.any(Location.id == location_id))
    query = query.order_by(Chapter.chapter_num)
    pagination, per_page = get_pagination(
        query, default_per_page=CHAPTERS_PER_PAGE)
    return envelope(pagination, per_page, _chapters_json(pagination.items))


@api.route('/chapters/<int:chapter_num>', methods=['GET'])
def chapter_detail(chapter_num):
    c = (
        Chapter.query
        .filter(Chapter.chapter_num == chapter_num,
                Chapter.is_deleted.is_(False))
        .first_or_404()
    )
    return jsonify(_chapters_json([c])[0])


# --------------------------------------------------------------------------
# Relationships / Relationship Types
# --------------------------------------------------------------------------

def _relationship_json(r):
    t = r.relationship_type
    c1, c2 = r.character1, r.character2
    end1 = dict(ser.character_ref(c1),
                label=t.end_label(1, c1.sex) or t.name)
    end2 = dict(ser.character_ref(c2),
                label=(t.end_label(2, c2.sex)
                       or t.end_label(1, c2.sex) or t.name))
    return {
        'id': r.id,
        'type': {'id': t.id, 'name': t.name,
                 'is_symmetric': t.is_symmetric},
        'character1': end1,
        'character2': end2,
    }


@api.route('/relationships', methods=['GET'])
def relationships():
    query = (
        Relationship.query
        .join(Relationship.relationship_type)
        .options(
            selectinload(Relationship.character1),
            selectinload(Relationship.character2),
            selectinload(Relationship.relationship_type),
        )
    )
    character_id = int_arg('character_id')
    if character_id is not None:
        query = query.filter(
            (Relationship.character1_id == character_id)
            | (Relationship.character2_id == character_id))
    type_id = int_arg('relationship_type_id')
    if type_id is not None:
        query = query.filter(Relationship.relationship_type_id == type_id)
    query = query.order_by(RelationshipType.name, Relationship.id)

    pagination, per_page = get_pagination(query)
    items = [_relationship_json(r) for r in pagination.items
             if not (r.character1.is_deleted or r.character2.is_deleted)]
    return envelope(pagination, per_page, items)


def _relationship_type_json(t, usage=None):
    return {
        'id': t.id,
        'name': t.name,
        'side1_label': t.side1_label or '',
        'side1_label_female': t.side1_label_female or '',
        'side2_label': t.side2_label or '',
        'side2_label_female': t.side2_label_female or '',
        'is_symmetric': t.is_symmetric,
        'usage_count': usage,
    }


@api.route('/relationship-types', methods=['GET'])
def relationship_types():
    query = _tag_shaped_query(RelationshipType)
    pagination, per_page = get_pagination(query)
    ids = [t.id for t in pagination.items]
    counts = {}
    if ids:
        counts = dict(
            db.session.query(Relationship.relationship_type_id,
                             func.count(Relationship.id))
            .filter(Relationship.relationship_type_id.in_(ids))
            .group_by(Relationship.relationship_type_id)
            .all()
        )
    return envelope(pagination, per_page,
                    [_relationship_type_json(t, counts.get(t.id, 0))
                     for t in pagination.items])


@api.route('/relationship-types/<int:type_id>', methods=['GET'])
def relationship_type_detail(type_id):
    t = (
        RelationshipType.query
        .filter(RelationshipType.id == type_id,
                RelationshipType.is_deleted.is_(False),
                RelationshipType.is_hidden.is_(False))
        .first_or_404()
    )
    usage = Relationship.query.filter_by(relationship_type_id=t.id).count()
    return jsonify(_relationship_type_json(t, usage))


# --------------------------------------------------------------------------
# Year Maps / Annotations (public only)
# --------------------------------------------------------------------------

from tools.book_parser import (  # noqa: E402
    annotation_section_canonical, annotation_section_hash,
)


def _year_map_json(m):
    factions = []
    for f in m.factions:
        if f.is_hidden:
            continue
        entry = ser.faction_ref(f)
        entry['leaders'] = [ser.character_ref(c) for c in f.leaders
                            if not c.is_deleted]
        factions.append(entry)
    return {
        'year': m.year,
        'image': url_for('static', filename=m.static_path),
        'source_site': m.source_site or '',
        'source_url': m.source_url or '',
        'factions': factions,
    }


@api.route('/year-maps', methods=['GET'])
def year_maps():
    query = (
        YearMap.query
        .options(selectinload(YearMap.factions)
                 .selectinload(Faction.leaders))
        .order_by(YearMap.year)
    )
    year_from = int_arg('year_from')
    if year_from is not None:
        query = query.filter(YearMap.year >= year_from)
    year_to = int_arg('year_to')
    if year_to is not None:
        query = query.filter(YearMap.year <= year_to)
    pagination, per_page = get_pagination(query)
    return envelope(pagination, per_page,
                    [_year_map_json(m) for m in pagination.items])


@api.route('/year-maps/<int:year>', methods=['GET'])
def year_map_detail(year):
    m = (
        YearMap.query
        .filter(YearMap.year == year)
        .options(selectinload(YearMap.factions)
                 .selectinload(Faction.leaders))
        .first_or_404()
    )
    return jsonify(_year_map_json(m))


def _annotation_json(a):
    return {
        'id': a.id,
        'chapter_num': a.chapter.chapter_num if a.chapter else None,
        'chapter_title': (a.chapter.name or '') if a.chapter else '',
        # Consumers can group entries into paragraph threads by this key
        # — it's the same content-addressed hash the site uses.
        'thread_key': annotation_section_hash(
            annotation_section_canonical(a.section_text)),
        'section_text': a.section_text,
        'body': a.body,
        'author': a.created_by,   # shown publicly on chapter pages too
        'created_at': a.created_at.isoformat() if a.created_at else None,
        'characters': [ser.character_ref(c) for c in a.characters
                       if not c.is_deleted],
        'locations': [ser.location_ref(l) for l in a.locations
                      if not l.is_deleted],
    }


@api.route('/annotations', methods=['GET'])
def annotations():
    """PUBLIC annotations only — the is_public filter here is the privacy
    boundary; private admin threads must never be serialized."""
    query = (
        Annotation.query
        .filter(Annotation.is_public.is_(True),
                Annotation.is_deleted.is_(False))
        .join(Chapter, Chapter.id == Annotation.chapter_id)
        .options(
            selectinload(Annotation.chapter),
            selectinload(Annotation.characters),
            selectinload(Annotation.locations),
        )
        .order_by(Chapter.chapter_num, Annotation.created_at)
    )
    chapter_num = int_arg('chapter_num')
    if chapter_num is not None:
        query = query.filter(Chapter.chapter_num == chapter_num)
    pagination, per_page = get_pagination(query)
    return envelope(pagination, per_page,
                    [_annotation_json(a) for a in pagination.items])


# --------------------------------------------------------------------------
# Province Maps — per-province map images + hand-placed overlays
# --------------------------------------------------------------------------

from app.models import ProvinceMap, ProvinceMapPlacement  # noqa: E402


def _province_map_json(m, placement_counts=None, detail=False):
    payload = {
        'id': m.id,
        'province': ser.location_ref(m.location),
        'label': m.label or '',
        'image': url_for('static', filename=m.static_path),
        'source_site': m.source_site or '',
        'source_url': m.source_url or '',
    }
    if placement_counts is not None:
        payload['placement_count'] = placement_counts.get(m.id, 0)
    if detail:
        rows = (
            ProvinceMapPlacement.query
            .filter_by(province_map_id=m.id)
            .options(selectinload(ProvinceMapPlacement.location)
                     .selectinload(Location.location_type))
            .all()
        )
        payload['placements'] = [
            {
                'location': ser.location_ref(p.location),
                'kind': p.kind,
                'geometry': p.geometry,
            }
            for p in rows
            if p.location is not None and not p.location.is_deleted
        ]
        payload['placement_count'] = len(payload['placements'])
    return payload


@api.route('/province-maps', methods=['GET'])
def province_maps():
    query = (
        ProvinceMap.query
        .options(selectinload(ProvinceMap.location)
                 .selectinload(Location.location_type))
        .order_by(ProvinceMap.location_id, ProvinceMap.label,
                  ProvinceMap.id)
    )
    location_id = int_arg('location_id')
    if location_id is not None:
        query = query.filter(ProvinceMap.location_id == location_id)
    pagination, per_page = get_pagination(query)
    ids = [m.id for m in pagination.items]
    counts = {}
    if ids:
        counts = dict(
            db.session.query(ProvinceMapPlacement.province_map_id,
                             func.count(ProvinceMapPlacement.id))
            .filter(ProvinceMapPlacement.province_map_id.in_(ids))
            .group_by(ProvinceMapPlacement.province_map_id)
            .all()
        )
    return envelope(pagination, per_page,
                    [_province_map_json(m, placement_counts=counts)
                     for m in pagination.items])


@api.route('/province-maps/<int:map_id>', methods=['GET'])
def province_map_detail(map_id):
    m = (
        ProvinceMap.query
        .filter(ProvinceMap.id == map_id)
        .options(selectinload(ProvinceMap.location)
                 .selectinload(Location.location_type))
        .first_or_404()
    )
    return jsonify(_province_map_json(m, detail=True))
