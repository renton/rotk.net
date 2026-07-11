"""Public read-only JSON API (mounted at /api/v1).

GET-only. Exposes the site's public data with rich joins so an external
consumer (the planned MCP server) can pull a resource and its related
records in one request. Admin-only data is NEVER served here: no users,
no edit log, no private annotations, no audit columns — see
serializers.py for the exclusion rules and registry.py for the endpoint
catalogue (which also drives the /admin/api-explorer page).
"""
from flask import Blueprint

api = Blueprint('api', __name__)

from . import views  # noqa: E402,F401 — route registration side-effect
