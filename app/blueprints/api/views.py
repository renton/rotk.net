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
