# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

`rotk.net` is a Flask web app that hosts an annotated, browsable edition of *Romance of the Three Kingdoms* (Luo Guanzhong, ~1300, Brewitt-Taylor translation). It scrapes the public-domain text from `threekingdoms.com` and a character index from Wikipedia, stores them in PostgreSQL, and renders chapters with inline character "tagging" (clickable badges that link the prose to a character record).

The site is single-tenant (one book), small-traffic, and most of the surface is read-only. The only write paths are admin character/faction/role editing and user login.

## Stack

- **Backend:** Flask 3.1 (app factory pattern), SQLAlchemy 2.0, Flask-Login, Flask-WTF, Flask-Talisman, Bootstrap-Flask
- **DB:** PostgreSQL 16 via `psycopg[binary]` (`postgresql+psycopg://...`). Local dev runs a bundled `db` service; production uses the shared cluster from [`stateful_boilerplate`](../stateful_boilerplate) — see the README for the override pattern.
- **Frontend:** Server-rendered Jinja2 + Bootstrap 5 CSS/JS from CDN. No bundler, no SPA. One CSS file (`app/static/styles.css`) with effectively no custom styling.
- **Scraping:** `requests` + `beautifulsoup4`
- **Serving:** gunicorn behind Caddy (provided by `stateful_boilerplate`) in prod; `flask run` in dev
- **Containers:** Docker + docker-compose. Single base `docker-compose.yml`; production gets a `docker-compose.override.yml` on the VPS that swaps the bundled `db` for shared postgres and joins the `shared` docker network.

## Architecture

```
rotk.py                  # Entry point: app instance, CLI commands, global error handlers, after_request CSP
config.py                # Config classes (Development, Production); reads .env via python-dotenv

app/
  __init__.py            # create_app() factory; initializes extensions + registers blueprints
  models/
    abstract.py          # AbstractObject (id/name/aliases/timestamps/soft-delete) + AbstractTag
    character.py         # Character, Link, Role, Faction, Portrait (+ association tables)
    chapter.py           # Chapter (name + content + chapter_num + many-to-many to Character)
    auth.py              # User, AnonymousUser, login_manager hooks
    event.py / location.py  # Empty stubs (commented placeholders only)
  blueprints/
    main/views.py        # Index (TOC), chapter view, character listing/edit, faction/role listing/edit
    main/forms.py        # CharacterFilterForm, EditCharacterForm, EditFactionForm, EditRoleForm
    auth/views.py        # login, logout, register, confirm, forgot/reset password, change password/email
    auth/forms.py        # Login, Registration, ForgotPassword, ResetPassword, ChangePassword, ChangeEmail
    auth/emails.py       # send_email() helper (multipart .txt + .html; suppresses send when SMTP not configured)
    admin/views.py       # /admin/users + toggle-admin (admin_required)
  templates/             # Jinja2: book/, characters/, factions/, roles/, auth/, errors/
  static/                # styles.css (1 rule), favicon, placeholder portrait

tools/
  scraper.py             # scrape_rotk_book() + scrape_rotk_characters()
  book_parser.py         # get_characters_for_chapter(), build_needle_pattern(), build_name_ref_html()
  dbm.py                 # DbManager helper (mostly unused; has bugs — see ISSUES.md)
  validators.py          # Hex colour validator
  decorators.py          # admin_required (BROKEN — see ISSUES.md)

migrations/              # Empty. Flask-Migrate is imported but commented out.
db-data/                 # Postgres data volume for local dev (gitignored)
```

## How data flows

1. **Bootstrap:** `flask create-all` creates schema, then `flask scrape-book` and `flask scrape-characters` populate from the web.
2. **Character ↔ Chapter linking is materialised by a CLI command.** Run `flask build-chapter-character-association` after scraping. `get_characters_for_chapter()` reads from the populated `chapter_character` table; if the table is empty, it falls back to regex-scanning every character against the chapter text on the fly.
3. **Inline tagging** (`build_name_ref_html`) replaces matched names in the chapter HTML with a `<span class="character-ref">` that has an `onclick` to a global JS `show_character()`.

## Running it

### Dev

```bash
cp .env.example .env       # fill in SECRET_KEY and POSTGRES_PASSWORD (any value for local dev)
docker-compose up          # serves on http://localhost:80
docker-compose exec app flask create-all          # creates schema
docker-compose exec app flask scrape-book         # ~120 HTTP fetches
docker-compose exec app flask scrape-characters   # ~26 HTTP fetches
docker-compose exec app flask build-chapter-character-association
```

The app connects as the `rotk_app` role, which owns the `rotk_net` database and thus has DDL privileges on it. No separate root/app distinction needed (unlike the previous MySQL setup).

Notes:
- `FLASK_ENV=development` is set in `docker-compose.yml`. CSRF is disabled in dev (`WTF_CSRF_ENABLED = False`).
- `Talisman(force_https=True)` is applied unconditionally — local HTTP will get HSTS-upgraded by the browser after the first visit. Use an incognito window if you hit redirect loops.
- `SQLALCHEMY_ECHO = True` is on in the base config, so dev logs include every SQL statement.

### Prod

Production lives on a single VPS running `stateful_boilerplate` (Caddy + shared postgres + shared redis). Deploy this project as a child:

1. Carve out the postgres role+DB on the shared cluster (one-off).
2. Drop a `docker-compose.override.yml` on the VPS that deletes the bundled `db`, joins the `shared` network, and points `POSTGRES_HOST=postgres`.
3. Add a site block to the boilerplate's `caddy/Caddyfile` reverse-proxying the app container.
4. Run the data-population CLI commands once.

Full walkthrough in `README.md`.

## CLI commands (defined in `rotk.py`)

| Command | What it does |
|---|---|
| `flask create-all` | `db.create_all()` — create schema |
| `flask scrape-book` | Pull all 120 chapters from threekingdoms.com |
| `flask scrape-characters` | Pull characters from Wikipedia A–Z pages, populate factions + roles |
| `flask build-chapter-character-association` | Populate the chapter_character join table by regex-scanning each chapter; needs to run after scrape-* |
| `flask make-admin EMAIL` | Promote a user to admin (also marks them confirmed) |
| `flask create-user EMAIL USERNAME [--admin]` | Create a user directly; prompts for the password |
| `flask deploy` | No-op — `pass` in body (called by `boot.sh`) |

## Conventions worth knowing

- **Soft delete** via `is_deleted` on `AbstractObject`. Use `Model.get_all_active()` to filter.
- **Case-sensitive name matching** is intentional — `name`/`aliases` columns use the Postgres `C` collation (byte-wise comparison) so `Cao` and `cao` (and `ü` vs `u`) are distinct. The previous MySQL incarnation used `utf8mb4_bin` for the same effect. This is why `flask scrape-characters` lowercases roles but NOT factions.
- **`sort_order=-1` on `mapped_column`** is used to keep inherited columns to the left in the physical table layout.
- **No Flask-Migrate.** Schema changes today require dropping/recreating. Re-enabling Alembic is on the wishlist (see ISSUES.md).
- **Admin gate** is `is_administrator` AND `confirmed` (both columns on `User`), enforced by `@admin_required`. First admin is bootstrapped via `flask make-admin <email>` or `flask create-user <email> <username> --admin`. After that the admin/users page promotes/demotes other users.
- **Email** is via Flask-Mail over SMTP. With no `MAIL_SERVER` configured, outbound mail is logged to stderr instead — dev works out of the box.

## Known landmines

These are flagged in detail in `ISSUES.md`. The short list:

- `tools/decorators.py::admin_required` lets **anonymous users through** — `current_user.is_administrator` is a column on `User` (bool) but a *method* on `AnonymousUser`; `not <bound method>` is always `False`. Treat all `@admin_required` routes as effectively unprotected until fixed.
- `tools/dbm.py` has two import/scope bugs (`inspect` not imported; bare `db` used instead of `self.db`).
- `AbstractObject.cleaned_name` and `__repr__` reference `self.display_name` which doesn't exist.
- `rotk.py` adds its own CSP via `@app.after_request` that overrides the (looser) one set by Talisman in `create_app`. The stricter one drops `'unsafe-inline'` for scripts, which kills the inline `onclick` used by the character-ref spans. Both CSPs end up in the response — the after_request one wins for the listed directives.
- Character name fields are typo'd as `courtesty_name` (and `chinese_courtesty_name`) throughout models, forms, and templates. Renaming is a coordinated change.
- `app/templates/auth/register.html` imports `bootstrap/wtf.html` (Flask-Bootstrap 3 path); the app uses Bootstrap-Flask 5 which exposes `bootstrap5/form.html`. The register template will 500 — but no route renders it, so it doesn't bite yet.

## Things to ask before doing

- **Don't run scrapers without confirming.** They hit external sites ~150 times and overwrite/duplicate rows depending on existing state. The current scraper has no upsert logic — re-running will throw IntegrityErrors on the unique constraint and skip rows.
- **Don't enable Flask-Migrate retroactively** without an Alembic baseline plan — `db.create_all()` has been the source of truth, and current schema may not match what a fresh autogenerate emits.
- **The MySQL → Postgres migration** (May 2026) changed: the DB URL builder in `config.py`, the `collation` argument in `app/models/abstract.py` (`utf8mb4_bin` → `C`), the bundled `db` service in `docker-compose.yml` (mysql:8.4 → postgres:16-alpine), `.env.example` (`MYSQL_*` → `POSTGRES_*`), and the requirements (`mysqlclient` / `mysql-connector` → `psycopg[binary]`). The DB was renamed `rotk.net` → `rotk_net` (no dot) to avoid postgres quoting hassles. `docker-compose.prod.yml`, `docker-compose.ambrose.yml`, `db-init/`, and the `nginx/` config were deleted — production now uses `stateful_boilerplate` for TLS/proxy.

## Memory

The auto-memory store lives at `~/.claude/projects/-home-renlawrence-Desktop-dev-rotk-net/memory/`. Use it for things that should persist across sessions (user preferences, project decisions). Don't store anything in memory that's already derivable from the code or git history.
