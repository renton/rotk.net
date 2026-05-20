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


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    CHARACTERS_PER_PAGE = 50
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = True

    @staticmethod
    def init_app(app):
        pass

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):

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
