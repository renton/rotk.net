from functools import wraps
from flask import abort
from flask_login import current_user


def admin_required(f):
    """Restrict a view to confirmed administrators. Anonymous and
    unconfirmed-or-non-admin authenticated users get a 403."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if (
            not current_user.is_authenticated
            or not current_user.is_administrator
            or not current_user.confirmed
        ):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
