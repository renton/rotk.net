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

    Two environments:
      * Local compose db — POSTGRES_USER is the container superuser, so
        auto-creation just works.
      * Shared cluster (ambrose/prod-style) — rotk_app deliberately
        CANNOT create databases. Auto-creation fails; the operator runs
        the one-time CREATE DATABASE below as the postgres superuser,
        after which this becomes a no-op.
    """
    dbname = uri.rsplit('/', 1)[-1].split('?')[0]
    admin_uri = uri.rsplit('/', 1)[0] + '/postgres'
    engine = sa.create_engine(admin_uri, isolation_level='AUTOCOMMIT')
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {'n': dbname},
            ).scalar()
            if exists:
                return
            try:
                conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
            except sa.exc.ProgrammingError as e:
                if 'InsufficientPrivilege' not in type(getattr(e, 'orig', e)).__name__ \
                        and 'permission denied' not in str(e).lower():
                    raise
                pytest.exit(
                    f"The role in POSTGRES_USER can't create databases on "
                    f"this cluster (expected on the shared prod cluster). "
                    f"One-time setup as the postgres superuser:\n\n"
                    f"  cd ~/stateful_boilerplate && docker compose exec -T "
                    f"postgres psql -U postgres -c "
                    f"'CREATE DATABASE {dbname} OWNER rotk_app;'\n\n"
                    f"Then re-run pytest.",
                    returncode=4,
                )
    finally:
        engine.dispose()


def _attach_cli_commands(application):
    """The project's @app.cli.command()s are registered on rotk.py's
    module-level app (which is built with the DEV config and must never
    be used in tests). Importing rotk creates that app object but makes
    NO database connection — SQLAlchemy connects lazily. We copy the
    click command objects onto the TEST app; their bodies use `db` and
    the models, which resolve through whatever app context the CLI
    runner provides — i.e. the test app and therefore the test DB."""
    import rotk  # noqa: F401  (import side effect: registers commands on rotk.app)
    for name, cmd in rotk.app.cli.commands.items():
        if name not in application.cli.commands:
            application.cli.add_command(cmd, name)


@pytest.fixture(scope='session')
def app():
    """Session-scoped Flask app bound to the guarded test database,
    with a freshly created schema."""
    application = create_app('testing')
    uri = application.config['SQLALCHEMY_DATABASE_URI']
    _assert_test_database(uri)
    _ensure_test_database_exists(uri)
    _attach_cli_commands(application)

    @application.teardown_request
    def _clear_flask_login_cache(exc=None):
        # The db_session fixture holds ONE app context open across the
        # whole test, so Flask reuses it for every test-client request
        # instead of pushing a fresh one per request (Flask only pushes
        # a new app context when none is active for the same app).
        # Flask-Login caches the resolved user on g._login_user — which
        # lives on that shared app context — so without this hook the
        # first client to authenticate leaks its user into every later
        # request in the same test, regardless of which client (or no
        # cookie at all) sends it. Symptom that found this: an
        # "anonymous" GET rendered admin-only content, including
        # private annotations in the payload. Popping the cache after
        # each request forces re-resolution from each request's own
        # session cookie, matching production behaviour (where every
        # request has a fresh app context and g).
        from flask import g
        g.pop('_login_user', None)

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
    """Function-scoped savepoint-rollback isolation.

    CRITICAL detail (found the hard way in shakeout round 2):
    Flask-SQLAlchemy's custom Session.get_bind() resolves the bind by
    metadata bind_key from `db.engines` and IGNORES a `bind=connection`
    passed to the sessionmaker — so the plain-SQLAlchemy recipe silently
    writes through the real engine and COMMITS FOR REAL (tests leak
    into each other). The documented FSA recipe instead replaces the
    ENGINE ENTRY in `db.engines` with the transaction-holding
    connection, so get_bind hands every session the connection and
    join_transaction_mode='create_savepoint' turns application commits
    into savepoint releases. Teardown rolls the outer transaction back
    and restores the engine entry."""
    with app.app_context():
        engines = _db.engines           # per-app {bind_key: engine} dict
        engine = engines[None]
        connection = engine.connect()
        transaction = connection.begin()
        engines[None] = connection      # <-- the load-bearing line

        original_session = _db.session
        session = _db._make_scoped_session(
            options=dict(join_transaction_mode='create_savepoint'))
        _db.session = session

        try:
            yield session
        finally:
            _db.session = original_session
            session.remove()
            transaction.rollback()
            connection.close()
            engines[None] = engine      # restore the real engine


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


@pytest.fixture(autouse=True)
def _assert_engine_is_test_db(app):
    """Belt-and-braces: EVERY test re-verifies the live engine points at
    a *_test database before it runs. If a future refactor breaks the
    TestingConfig wiring, the whole suite refuses to run rather than
    silently writing to live data."""
    with app.app_context():
        _assert_test_database(str(_db.engine.url))
    yield


@pytest.fixture(autouse=True)
def _no_favicon_network(monkeypatch):
    """add_owner_url best-effort-fetches a favicon over the network when
    the admin leaves the field blank. Stub it for EVERY test so no HTTP
    request ever leaves the suite; the favicon tests that want the real
    function re-patch it themselves with a mocked requests layer."""
    import tools.favicon_fetcher
    monkeypatch.setattr(tools.favicon_fetcher, 'fetch_favicon',
                        lambda target_url, static_folder: None)
