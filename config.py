import os
basedir = os.path.abspath(os.path.dirname(__file__))


def _database_uri():
    # Use the least-privileged app user at runtime. Root is reserved for
    # DDL (create-all, migrations) — invoke those with MYSQL_USE_ROOT=1.
    if os.environ.get("MYSQL_USE_ROOT") == "1":
        user = "root"
        password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    else:
        user = os.environ.get("MYSQL_APP_USER", "rotk_app")
        password = os.environ.get("MYSQL_APP_PASSWORD", "")
    host = os.environ.get("MYSQL_HOST", "db")
    return f"mysql+mysqldb://{user}:{password}@{host}/rotk.net"


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

    @staticmethod
    def init_app(app):
        pass


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True

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
    'default': DevelopmentConfig,
}
