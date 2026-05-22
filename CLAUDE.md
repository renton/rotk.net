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
- **Containers:** Docker + docker-compose. Single base `docker-compose.yml`. Production layers `examples/ambrose/docker-compose.override.yml` on top (via `-f` or `COMPOSE_FILE=`) to swap the bundled `db` for shared postgres, drop the dev bind-mount, and join the `shared` docker network. The overlay deliberately does NOT live at the repo root so it doesn't auto-apply on developer laptops.

## Architecture

```
rotk.py                  # Entry point: app instance, CLI commands, global error handlers
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
  dbm.py                 # DbManager helper (mostly unused)
  validators.py          # Hex colour validator
  decorators.py          # admin_required (authenticated + is_administrator + confirmed)

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
- `FLASK_ENV=development` is set in `docker-compose.yml`. CSRF is on (Flask-WTF default).
- TLS, HTTP→HTTPS redirect, HSTS, and the rest of the standard security headers come from the boilerplate's Caddy in production. The app sets CSP via a small `after_request` hook in `app/__init__.py` and otherwise emits plain HTTP.
- `SQLALCHEMY_ECHO = True` is on in the base config, so dev logs include every SQL statement (and prod logs do too — open issue, see ISSUES.md #28).

### Prod

Production lives on a single VPS running `stateful_boilerplate` (Caddy + shared postgres + shared redis). Deploy this project as a child:

1. Carve out the postgres role+DB on the shared cluster (one-off).
2. On the VPS, apply the in-repo overlay at `examples/ambrose/docker-compose.override.yml` with `-f` (or `COMPOSE_FILE=docker-compose.yml:examples/ambrose/docker-compose.override.yml` in `.env`). It deletes the bundled `db`, joins the `shared` network, drops the dev bind-mount, and points `POSTGRES_HOST=postgres`.
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
| `flask scrape-koei-images` | Scrape character portraits from koei.fandom.com into `app/static/portraits/` + `Portrait` rows |
| `flask randomize-faction-colours` | Randomize bg/font/border on every faction; font chosen for WCAG-readable contrast |
| `flask make-admin EMAIL` | Promote a user to admin (also marks them confirmed) |
| `flask create-user EMAIL USERNAME [--admin]` | Create a user directly; prompts for the password |
| `flask deploy` | No-op — `pass` in body (called by `boot.sh`) |

**When you add a new `@app.cli.command()`, also add it to this table AND to the matching table in `README.md`.** The README table is the one users see; this one is what future Claude sessions read first.

## Conventions worth knowing

- **Soft delete** via `is_deleted` on `AbstractObject`. Use `Model.get_all_active()` to filter.
- **Case-sensitive name matching** is intentional — `name`/`aliases` columns use the Postgres `C` collation (byte-wise comparison) so `Cao` and `cao` (and `ü` vs `u`) are distinct. The previous MySQL incarnation used `utf8mb4_bin` for the same effect. This is why `flask scrape-characters` lowercases roles but NOT factions.
- **`sort_order=-1` on `mapped_column`** is used to keep inherited columns to the left in the physical table layout.
- **No Flask-Migrate.** Schema changes today require dropping/recreating. Re-enabling Alembic is on the wishlist (see ISSUES.md).
- **Admin gate** is `is_administrator` AND `confirmed` (both columns on `User`), enforced by `@admin_required`. First admin is bootstrapped via `flask make-admin <email>` or `flask create-user <email> <username> --admin`. After that the admin/users page promotes/demotes other users.
- **Email** is via Flask-Mail over SMTP. With no `MAIL_SERVER` configured, outbound mail is logged to stderr instead — dev works out of the box.

## Known landmines

See `ISSUES.md` for the full running list. Highlights still open:

- Character name fields are typo'd as `courtesty_name` (and `chinese_courtesty_name`) throughout models, forms, and templates. Renaming is a coordinated change (#19).
- Birth/death dates are stored as `String(4)` and can't represent BC years or be range-queried (#20).
- No tests, no Alembic — schema changes still require drop/recreate + re-scrape (#25, #26).

## Things to ask before doing

- **Don't run scrapers without confirming.** They hit external sites ~150 times and overwrite/duplicate rows depending on existing state. The current scraper has no upsert logic — re-running will throw IntegrityErrors on the unique constraint and skip rows.
- **Don't enable Flask-Migrate retroactively** without an Alembic baseline plan — `db.create_all()` has been the source of truth, and current schema may not match what a fresh autogenerate emits.
- **The MySQL → Postgres migration** (May 2026) changed: the DB URL builder in `config.py`, the `collation` argument in `app/models/abstract.py` (`utf8mb4_bin` → `C`), the bundled `db` service in `docker-compose.yml` (mysql:8.4 → postgres:16-alpine), `.env.example` (`MYSQL_*` → `POSTGRES_*`), and the requirements (`mysqlclient` / `mysql-connector` → `psycopg[binary]`). The DB was renamed `rotk.net` → `rotk_net` (no dot) to avoid postgres quoting hassles. `docker-compose.prod.yml`, `docker-compose.ambrose.yml`, `db-init/`, and the `nginx/` config were deleted — production now uses `stateful_boilerplate` for TLS/proxy.

## Memory

The auto-memory store lives at `~/.claude/projects/-home-renton-Desktop-dev-codedev-webdev-rotk-net/memory/`. Use it for things that should persist across sessions (user preferences, project decisions). Don't store anything in memory that's already derivable from the code or git history.
