"""Shared pytest fixtures for the rotk.net backend suite.

SAFETY MODEL
============
Everything here is designed so the suite can NEVER touch live data:

1. The app is built with `create_app('testing')`; TestingConfig hardcodes
   the database NAME to `rotk_net_test` (config.py) — it is never derived
   from POSTGRES_DB.
2. `_assert_test_database` re-checks the resolved URI before any DDL/DML
   and `pytest.exit()`s the whole run if the DB name doesn't end in
   `_test`. Belt and braces: even if someone edits TestingConfig badly,
   the guard trips.
3. The test database is created on demand (CREATE DATABASE) by connecting
   to the maintenance `postgres` DB; schema is drop_all/create_all'd once
   per session — only ever against the guarded URI.
4. Per-test writes happen inside a savepoint-joined session that is
   rolled back in teardown (the documented Flask-SQLAlchemy 3.x recipe),
   so tests are fully isolated from each other and nothing persists.

RUNNING
=======
Inside the compose app container (deps + db-host resolution included):

    docker compose exec app pytest -q

The compose `db` publishes 127.0.0.1:5432, so a host-side venv with
POSTGRES_HOST=localhost also works.
"""
import os
import sys

import pytest
import sqlalchemy as sa

# Make the project root importable when pytest is invoked from anywhere.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app import create_app, db as _db  # noqa: E402
from tests import factories  # noqa: E402  (re-exported for convenience)


def _assert_test_database(uri):
    """Hard guard: refuse to run against anything that isn't a *_test DB."""
    dbname = uri.rsplit('/', 1)[-1].split('?')[0]
    if not dbname.endswith('_test'):
        pytest.exit(
            f"SAFETY: refusing to run tests against database {dbname!r} "
            f"(must end with '_test'). Check TestingConfig.",
            returncode=3,
        )


def _ensure_test_database_exists(uri):
    """CREATE DATABASE rotk_net_test if missing, via the maintenance DB.
    The compose postgres image makes POSTGRES_USER a superuser, so the
    app role can create databases in dev. No-op if it already exists."""
    dbname = uri.rsplit('/', 1)[-1].split('?')[0]
    admin_uri = uri.rsplit('/', 1)[0] + '/postgres'
    engine = sa.create_engine(admin_uri, isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {'n': dbname},
            ).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


@pytest.fixture(scope='session')
def app():
    """Session-scoped Flask app bound to the guarded test database,
    with a freshly created schema."""
    application = create_app('testing')
    uri = application.config['SQLALCHEMY_DATABASE_URI']
    _assert_test_database(uri)
    _ensure_test_database_exists(uri)

    with application.app_context():
        _assert_test_database(str(_db.engine.url))
        _db.drop_all()
        _db.create_all()

    yield application

    with application.app_context():
        _db.session.remove()
        _db.engine.dispose()


@pytest.fixture()
def db_session(app):
    """Function-scoped session that joins an outer transaction via
    savepoints. Everything a test (or the routes it calls) commits is
    rolled back at teardown, so each test sees a pristine empty schema.

    Standard Flask-SQLAlchemy 3.x recipe: bind the scoped session to a
    connection that carries an open transaction, with
    join_transaction_mode='create_savepoint' so session.commit() inside
    application code only releases a savepoint."""
    with app.app_context():
        engine = _db.engine
        connection = engine.connect()
        transaction = connection.begin()

        original_session = _db.session
        session_options = dict(
            bind=connection,
            join_transaction_mode='create_savepoint',
        )
        session = _db._make_scoped_session(options=session_options)
        _db.session = session

        yield session

        _db.session = original_session
        session.remove()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(app, db_session):
    """Anonymous test client. Depends on db_session so any route-driven
    writes are rolled back too."""
    return app.test_client()


def _login(app, db_session, is_admin):
    """Create a confirmed user (admin or not) and return a logged-in
    client for them plus the user object."""
    user = factories.make_admin(db_session) if is_admin else factories.make_user(db_session)
    test_client = app.test_client()
    resp = test_client.post('/auth/login', data={
        'email': user.email,
        'password': factories.DEFAULT_PASSWORD,
    }, follow_redirects=True)
    assert resp.status_code == 200
    return test_client, user


@pytest.fixture()
def user_client(app, db_session):
    """Logged-in NON-admin client. Yields (client, user)."""
    return _login(app, db_session, is_admin=False)


@pytest.fixture()
def admin_client(app, db_session):
    """Logged-in confirmed-admin client. Yields (client, user)."""
    return _login(app, db_session, is_admin=True)


@pytest.fixture()
def cli_runner(app, db_session):
    """Click test runner for @app.cli.command() commands, sharing the
    rollback-isolated session."""
    return app.test_cli_runner()
