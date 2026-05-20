# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this project is

`rotk.net` is a Flask web app that hosts an annotated, browsable edition of *Romance of the Three Kingdoms* (Luo Guanzhong, ~1300, Brewitt-Taylor translation). It scrapes the public-domain text from `threekingdoms.com` and a character index from Wikipedia, stores them in MySQL, and renders chapters with inline character "tagging" (clickable badges that link the prose to a character record).

The site is single-tenant (one book), small-traffic, and most of the surface is read-only. The only write paths are admin character/faction/role editing and user login.

## Stack

- **Backend:** Flask 3.1 (app factory pattern), SQLAlchemy 2.0, Flask-Login, Flask-WTF, Flask-Talisman, Bootstrap-Flask
- **DB:** MySQL 8.4 via `mysqlclient` (`mysql+mysqldb://...`)
- **Frontend:** Server-rendered Jinja2 + Bootstrap 5 CSS/JS from CDN. No bundler, no SPA. One CSS file (`app/static/styles.css`) with effectively no custom styling.
- **Scraping:** `requests` + `beautifulsoup4`
- **Serving:** gunicorn behind nginx (TLS via certbot/Let's Encrypt) in prod; `flask run` in dev
- **Containers:** Docker + docker-compose (separate dev / prod compose files)

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
    auth/views.py        # login, logout only (register/reset views NOT implemented; forms exist)
    auth/forms.py        # Login, Registration, ChangePassword, PasswordReset*, ChangeEmail forms
  templates/             # Jinja2: book/, characters/, factions/, roles/, auth/, errors/
  static/                # styles.css (1 rule), favicon, placeholder portrait

tools/
  scraper.py             # scrape_rotk_book() + scrape_rotk_characters()
  book_parser.py         # get_characters_for_chapter(), build_needle_pattern(), build_name_ref_html()
  dbm.py                 # DbManager helper (mostly unused; has bugs — see ISSUES.md)
  validators.py          # Hex colour validator
  decorators.py          # admin_required (BROKEN — see ISSUES.md)

migrations/              # Empty. Flask-Migrate is imported but commented out.
nginx/nginx.conf         # Reverse proxy + TLS termination for prod
db-confs/                # MySQL conf overrides (empty in repo, gitignored)
db-data/                 # MySQL data volume (gitignored)
```

## How data flows

1. **Bootstrap:** `flask create-all` creates schema, then `flask scrape-book` and `flask scrape-characters` populate from the web.
2. **Character ↔ Chapter linking is implicit, not stored.** `get_characters_for_chapter()` scans the chapter text for every character's name/aliases/courtesy-name on every render. There is a `chapter_character` association table defined but it is never written to (and never queried for membership).
3. **Inline tagging** (`build_name_ref_html`) replaces matched names in the chapter HTML with a `<span class="character-ref">` that has an `onclick` to a global JS `show_character()`.

## Running it

### Dev

```bash
cp .env.example .env       # fill in MYSQL_ROOT_PASSWORD and SECRET_KEY
docker-compose up          # serves on http://localhost:80
docker-compose exec app flask create-all
docker-compose exec app flask scrape-book        # ~120 HTTP fetches
docker-compose exec app flask scrape-characters  # ~26 HTTP fetches
```

Notes:
- `FLASK_ENV=development` is set in `docker-compose.yml`. CSRF is disabled in dev (`WTF_CSRF_ENABLED = False`).
- `Talisman(force_https=True)` is applied unconditionally — local HTTP will get HSTS-upgraded by the browser after the first visit. Use an incognito window if you hit redirect loops.
- `SQLALCHEMY_ECHO = True` is on in the base config, so dev logs include every SQL statement.

### Prod

```bash
docker-compose -f docker-compose.prod.yml up -d
```

Requires Let's Encrypt certs on the host at `/etc/letsencrypt/live/rotk.net/`. nginx terminates TLS and proxies to gunicorn (3 workers, 240s timeout, `--reload`).

## CLI commands (defined in `rotk.py`)

| Command | What it does |
|---|---|
| `flask create-all` | `db.create_all()` — create schema |
| `flask scrape-book` | Pull all 120 chapters from threekingdoms.com |
| `flask scrape-characters` | Pull characters from Wikipedia A–Z pages, populate factions + roles |
| `flask build-chapter-characters` | Currently just prints characters for chapter 1 (debug stub) |
| `flask deploy` | No-op — `pass` in body (called by `boot.sh`) |

## Conventions worth knowing

- **Soft delete** via `is_deleted` on `AbstractObject`. Use `Model.get_all_active()` to filter.
- **Case-sensitive name matching** is intentional — `name`/`aliases` columns use `utf8mb4_bin` collation so `Cao` and `cao` are distinct. This is why `flask scrape-characters` lowercases roles but NOT factions.
- **`sort_order=-1` on `mapped_column`** is used to keep inherited columns to the left in the physical table layout.
- **No Flask-Migrate.** Schema changes today require dropping/recreating. Re-enabling Alembic is on the wishlist (see ISSUES.md).
- **Admin gate** is `is_administrator` (a column on `User`). There is currently no UI to set it — flip the bit in the DB directly.

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
- **Don't bump `mysql-connector` or remove it without checking** — it's pinned to a 2017 version, but is unused in code. Likely safe to drop; verify first.

## Memory

The auto-memory store lives at `~/.claude/projects/-home-renlawrence-Desktop-dev-rotk-net/memory/`. Use it for things that should persist across sessions (user preferences, project decisions). Don't store anything in memory that's already derivable from the code or git history.
