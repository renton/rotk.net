"""ORM event hooks that stamp `created_by` / `last_edited_by` on any
model that declares those columns.

How attribution is decided:

- Inside a Flask request with a logged-in user → that user's username.
- Anywhere else (CLI commands, scraper, async jobs, raw shell, etc.)
  → the literal string "rotk.net_system".

Plain strings (not FKs to user.id) are used on purpose: a deleted user
shouldn't make their old contributions un-attributable, and an
out-of-band stamp like "rotk.net_system" doesn't need a corresponding
User row.

Insert behaviour: `created_by` AND `last_edited_by` are both populated.

Update behaviour: `last_edited_by` is only overwritten when there IS a
logged-in user. CLI commands updating data (e.g. flask
recount-book-mentions, the periodic scraper) deliberately don't touch
this field — otherwise every batch job would clobber the admin
attribution on every row it scanned. `created_by` is never touched on
update.
"""
from sqlalchemy import event
from sqlalchemy.orm import Mapper


SYSTEM_USER = "rotk.net_system"


def _try_current_username():
    """Return the logged-in user's username, or None if there isn't one
    (no Flask request context / anonymous / current_user import failed).
    Wrapped in a broad try/except because this runs from mapper events
    that fire in arbitrary contexts including raw scripts and tests."""
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            return current_user.username
    except Exception:
        pass
    return None


@event.listens_for(Mapper, 'before_insert')
def _audit_on_insert(mapper, connection, target):
    cls = target.__class__
    username = _try_current_username() or SYSTEM_USER
    # `hasattr` on the class — checking the instance would always be True
    # since SQLAlchemy proxies any column attribute access.
    if hasattr(cls, 'created_by') and not getattr(target, 'created_by', None):
        target.created_by = username
    if hasattr(cls, 'last_edited_by') and not getattr(target, 'last_edited_by', None):
        target.last_edited_by = username


@event.listens_for(Mapper, 'before_update')
def _audit_on_update(mapper, connection, target):
    """Overwrite last_edited_by only when there's a real logged-in user.
    See module docstring for the rationale."""
    username = _try_current_username()
    if username is None:
        return
    cls = target.__class__
    if hasattr(cls, 'last_edited_by'):
        target.last_edited_by = username
