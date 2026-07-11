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
