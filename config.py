import os
basedir = os.path.abspath(os.path.dirname(__file__))


def _database_uri():
    # Postgres connection string. Env vars mirror standard libpq names so
    # any tooling that already reads them (psql, alembic, etc.) just works.
    # The role used here should be the least-privileged app user; DDL
    # (create_all, migrations) is run with the same role since it owns the
    # database it was created against.
    user = os.environ.get("POSTGRES_USER", "rotk_app")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "rotk_net")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


def _env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    CHARACTERS_PER_PAGE = 50
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = True

    # Force Jinja to re-stat templates on each render so edits show up on
    # browser refresh without a container restart. Negligible overhead for
    # this app's traffic level; default-False in prod gunicorn otherwise.
    TEMPLATES_AUTO_RELOAD = True

    # Hard cap on the size of any HTTP request body. Werkzeug returns 413
    # before our view sees an oversized upload. 12 MB gives some headroom
    # over the 10 MB per-portrait limit enforced in the upload route
    # (multipart boundary + other form fields add a few KB).
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024

    # Google Analytics 4 tracking ID (e.g. "G-XXXXXXXXXX"). Leave blank to
    # disable analytics — the base template skips the gtag snippet when
    # this is empty.
    GA_TRACKING_ID = os.environ.get('GA_TRACKING_ID', '')

    # --- Mail (Flask-Mail) ---
    # Any SMTP provider works (Mailgun, SendGrid, AWS SES, Postmark, Gmail).
    # If MAIL_SERVER is not set, MAIL_SUPPRESS_SEND defaults to True and
    # outgoing messages are logged instead of sent.
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = _env_bool('MAIL_USE_TLS', default=True)
    MAIL_USE_SSL = _env_bool('MAIL_USE_SSL', default=False)
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get(
        'MAIL_DEFAULT_SENDER', 'rotk.net <no-reply@rotk.net>'
    )
    MAIL_SUPPRESS_SEND = _env_bool(
        'MAIL_SUPPRESS_SEND',
        default=not bool(os.environ.get('MAIL_SERVER')),
    )

    # Branding values used inside email templates.
    APP_NAME = 'rotk.net'
    APP_BASE_URL = os.environ.get('APP_BASE_URL', '')

    # Token expirations (seconds).
    CONFIRM_TOKEN_TTL = 60 * 60 * 24   # 24h
    RESET_TOKEN_TTL = 60 * 60          # 1h
    EMAIL_CHANGE_TOKEN_TTL = 60 * 60   # 1h

    # --- Rate limiting (Flask-Limiter) ---
    # `memory://` keeps counters in each worker's process, which means
    # limits are per-worker — with 3 gunicorn workers the effective limit
    # is ~3x what's configured. Set RATELIMIT_STORAGE_URI to a shared
    # Redis (e.g. redis://:<password>@redis:6379/0) for global limits.
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    DEBUG = True


def _test_database_uri():
    """Test DB URI. The database NAME is hardcoded to `rotk_net_test`
    on purpose — never derived from POSTGRES_DB — so a mis-set env var
    can't point the test suite at live data. Host/port/user/password
    reuse the standard env vars so this works both inside the compose
    app container (host `db`) and from the host machine (the compose
    db publishes 127.0.0.1:5432)."""
    user = os.environ.get("POSTGRES_USER", "rotk_app")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/rotk_net_test"


class TestingConfig(Config):
    """pytest-only config. tests/conftest.py additionally hard-asserts
    the DB name ends in `_test` before any DDL/DML runs."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _test_database_uri()
    SQLALCHEMY_ECHO = False
    # Every POST route would 400 without a CSRF token otherwise; the
    # suite tests the routes' logic, not Flask-WTF's CSRF machinery.
    WTF_CSRF_ENABLED = False
    # The auth routes carry per-minute limits that a fast test run
    # would trip immediately.
    RATELIMIT_ENABLED = False
    # itsdangerous token generation + session signing need a key.
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'test-secret-key-not-for-prod'
    # Never send mail from tests regardless of env.
    MAIL_SUPPRESS_SEND = True


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    SQLALCHEMY_ECHO = False

    @classmethod
    def init_app(cls, app):
        Config.init_app(app)

        # log to stderr
        import logging
        from logging import StreamHandler
        file_handler = StreamHandler()
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
