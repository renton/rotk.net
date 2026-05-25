"""Audit-log wiring.

Registers `after_insert`, `after_update`, `after_delete` listeners on
SQLAlchemy's base `Mapper`, so every mapped class is covered. Each
listener does a direct `connection.execute(Edit.__table__.insert(...))`
inside the same flush that's currently running — so the audit row is
atomic with the change it documents.

User attribution:
  - Inside a request context: pulls `current_user.username` from
    Flask-Login if authenticated.
  - Outside (CLI, scripts, scrapers): falls back to 'rotk.net_system'.

Limitations (worth knowing before you trust this for compliance):
  - Bulk `Query.update()` / `Query.delete()` bypass ORM events and are
    NOT logged. The two places we use bulk update today
    (set_default_portrait, merge_faction's primary_faction switch) are
    documented in code; if you add more, log them explicitly.
  - M2M / one-to-many membership changes are best-effort: we inspect
    the parent's relationship history during after_update. Direct
    manipulation of the association row (rare) wouldn't go through
    after_update on either end.
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Mapper

from app import db
from app.models.edit import Edit


SYSTEM_USER_LABEL = 'rotk.net_system'

# Relationship directions we care about logging. MANYTOONE is excluded
# because the FK column already covers it via column_attrs.
_TRACKED_REL_DIRECTIONS = ('MANYTOMANY', 'ONETOMANY')


def _jsonable(val):
    """Coerce a column / relationship value into something JSONB can
    store. Datetimes become ISO strings; Decimals become floats;
    anything else exotic falls back to its str()."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (list, tuple)):
        return [_jsonable(v) for v in val]
    if isinstance(val, dict):
        return {str(k): _jsonable(v) for k, v in val.items()}
    return str(val)


def _current_user_info():
    """Return (user_id_or_None, user_label) for the actor of this edit."""
    try:
        from flask import has_request_context
    except Exception:
        return None, SYSTEM_USER_LABEL
    if not has_request_context():
        return None, SYSTEM_USER_LABEL
    try:
        from flask_login import current_user
        if getattr(current_user, 'is_authenticated', False):
            return current_user.id, current_user.username or current_user.email or 'unknown'
    except Exception:
        pass
    return None, SYSTEM_USER_LABEL


def _column_snapshot(target):
    """All column values on `target`, jsonable. Used for create/delete."""
    insp = inspect(target)
    out = {}
    for col_attr in insp.mapper.column_attrs:
        out[col_attr.key] = _jsonable(getattr(target, col_attr.key, None))
    return out


def _changed_columns(target):
    """Only columns that changed in this flush, with old + new."""
    insp = inspect(target)
    out = {}
    for col_attr in insp.mapper.column_attrs:
        hist = insp.attrs[col_attr.key].history
        if not hist.has_changes():
            continue
        old = hist.deleted[0] if hist.deleted else None
        new = hist.added[0] if hist.added else getattr(target, col_attr.key, None)
        out[col_attr.key] = {'old': _jsonable(old), 'new': _jsonable(new)}
    return out


def _changed_relationships(target):
    """Best-effort: which tracked-direction relationships saw membership
    changes during this flush. Skip lazy='dynamic' relationships
    (they don't expose useful history)."""
    insp = inspect(target)
    out = {}
    for rel in insp.mapper.relationships:
        if rel.direction.name not in _TRACKED_REL_DIRECTIONS:
            continue
        if rel.lazy == 'dynamic':
            # Dynamic relationships don't expose collection history in a
            # useful way; skip rather than risk firing extra queries.
            continue
        try:
            hist = insp.attrs[rel.key].history
        except Exception:
            continue
        if not hist.has_changes():
            continue
        added = [getattr(o, 'id', None) for o in (hist.added or [])]
        removed = [getattr(o, 'id', None) for o in (hist.deleted or [])]
        if added or removed:
            out[rel.key] = {'added': added, 'removed': removed}
    return out


def _emit(connection, target, action, changes):
    """Write the Edit row via the same connection as the original flush."""
    table = inspect(target).mapper.local_table
    user_id, user_label = _current_user_info()
    connection.execute(
        Edit.__table__.insert().values(
            target_type=table.name,
            target_id=getattr(target, 'id', None),
            action=action,
            user_id=user_id,
            user_label=user_label,
            changes=changes,
        )
    )


def _should_skip(target):
    """Don't log the audit log writing to itself."""
    return isinstance(target, Edit)


@event.listens_for(Mapper, 'after_insert')
def _on_insert(mapper, connection, target):
    if _should_skip(target):
        return
    _emit(connection, target, 'create', _column_snapshot(target))


@event.listens_for(Mapper, 'after_update')
def _on_update(mapper, connection, target):
    if _should_skip(target):
        return
    changes = _changed_columns(target)
    rels = _changed_relationships(target)
    if rels:
        changes['_relationships'] = rels
    if not changes:
        # No-op flush (e.g. SQLAlchemy flushed for cache, nothing changed).
        return
    _emit(connection, target, 'update', changes)


@event.listens_for(Mapper, 'after_delete')
def _on_delete(mapper, connection, target):
    if _should_skip(target):
        return
    _emit(connection, target, 'delete', _column_snapshot(target))
