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
rotk.py                  # Entry point: app instance, CLI commands, global error handlers
config.py                # Config classes (Development, Production); reads .env via python-dotenv

app/
  __init__.py            # create_app() factory; initializes extensions + registers blueprints
  models/
    abstract.py          # AbstractObject (id/name/aliases/timestamps/soft-delete/audit) + AbstractTag (+ icon + 3 colour cols)
    audit.py             # ORM event hooks stamping created_by / last_edited_by on every Model with those columns
    character.py         # Character, Link, Role, Faction, Portrait (+ association tables)
    chapter.py           # Chapter (name + content + chapter_num + M2M to Character / Event / Location)
    event.py             # Event (name, aliases, optional Location FK, optional EventType FK, geo override) + EventType (AbstractTag)
    location.py          # Location (name, aliases, lat/lng) — chapter↔location M2M attached here
    tag.py               # Tag + TagAssociation (polymorphic by target_type + target_id)
    url.py               # Url + UrlType (polymorphic Url; FA-iconed UrlType)
    match_exclusion.py   # MatchExclusion — per-snippet "don't inline-tag this match" for a (chapter, target_type, target_id)
    edit.py              # Edit (admin save audit log: model, row, field-by-field diffs)
    auth.py              # User, AnonymousUser, login_manager hooks
  blueprints/
    main/views.py        # Public + admin-edit routes for Character / Faction / Role / Event / Location;
                         #   chapter view (inline-tags characters + events + locations, applies per-snippet exclusions)
    main/forms.py        # EditCharacterForm, EditFactionForm, EditRoleForm, EditEventForm, EditLocationForm, AddUrlForm
    auth/views.py        # login, logout, register, confirm, forgot/reset password, change password/email
    auth/forms.py        # Login, Registration, ForgotPassword, ResetPassword, ChangePassword, ChangeEmail
    auth/emails.py       # send_email() helper (multipart .txt + .html; suppresses send when SMTP not configured)
    admin/views.py       # /admin/users, /admin/faq, /admin/duplicates, /admin/edits, /admin/tags,
                         #   /admin/url-types, /admin/event-types, /admin/image-manager,
                         #   /admin/chapter-associations, /admin/event-associations,
                         #   /admin/location-associations (+ per-snippet exclude / restore)
    admin/forms.py       # EditTagForm, EditUrlTypeForm, EditEventTypeForm, CreateUserForm
  templates/             # Jinja2: book/, characters/, factions/, roles/, events/, locations/, admin/, auth/, errors/
                         # Shared partials: _macros.html (badge_widget with icon prefix),
                         #   _url_section.html (External Links fieldset on edit pages),
                         #   _url_list.html (read-only URL list w/ favicon + UrlType badge)
  static/
    styles.css           # Sidebar sticky rules, event/location ref styling, sidebar-flash animation
    js/                  # chapter.js (refs click + link-style cookie + accordion-flash),
                         #   chapter_style.js (tag-style switcher, localStorage-backed),
                         #   admin_picker.js (datalist id resolver + auto-fill keywords field),
                         #   admin_confirm.js (data-confirm submit gate),
                         #   admin_colour_picker.js (Randomize palette button injector)

tools/
  scraper.py             # scrape_rotk_book() + scrape_rotk_characters()
  book_parser.py         # get_characters_for_chapter(), build_needle_pattern(), build_name_ref_html(),
                         #   build_event_ref_html(), build_location_ref_html(), find_*_mentions(),
                         #   load_match_exclusions()
  colours.py             # randomize_palette() — HSL-random bg, WCAG-readable font, hue-locked border
  favicon_fetcher.py     # Pull a URL's host favicon into static/favicons/<host>_favicon.ico
  image_scrapers/        # Per-source portrait scrapers (Koei via MediaWiki API)
  dbm.py                 # DbManager helper (mostly unused)
  validators.py          # Hex colour validator
  decorators.py          # admin_required (authenticated + is_administrator + confirmed)

migrations/              # Raw .sql files applied by `flask apply-migrations`.
                         # Numbered NNNN_description.sql; each is idempotent
                         # (IF NOT EXISTS / IF EXISTS / ON CONFLICT DO NOTHING).
                         # Already-applied filenames are tracked in the
                         # `_schema_migrations` table at runtime — re-running
                         # the command is safe.  Flask-Migrate / Alembic
                         # itself is NOT wired up; plain-SQL is the chosen
                         # migration system for this project.
db-data/                 # Postgres data volume for local dev (gitignored)
```

## How data flows

1. **Bootstrap:** `flask create-all` creates the tables, `flask apply-migrations` applies every SQL file in `migrations/`, then `flask scrape-book` and `flask scrape-characters` populate from the web. `seed-location-types` + `import-admin-divisions` seed the Location hierarchy from `data/3k_admin_divisions.csv` if you want the admin divisions pre-populated.
2. **Character ↔ Chapter linking is materialised by a CLI command.** Run `flask build-chapter-character-association` after scraping. `get_characters_for_chapter()` reads from the populated `chapter_character` table; if the table is empty, it falls back to regex-scanning every character against the chapter text on the fly.
3. **Inline tagging** at chapter render time. The chapter view builds one combined needle pattern out of:
    - Every associated character's `name + courtesy_name + aliases` → coloured pill via `build_name_ref_html()`
    - Every associated event's `name + aliases` → black-underlined span via `build_event_ref_html()` (clicking opens + flashes the *Events* accordion item)
    - Every associated location's `name + aliases` → same as events, via `build_location_ref_html()`
   The combined `pattern.sub()` runs once over the chapter HTML. Characters get first claim on any conflicting needle; events claim next; locations last.
4. **Per-snippet exclusions** (location only, currently) — admin can mark individual matches as bad on `/admin/location-associations`. Each exclusion stores a `(chapter, target_type, target_id, before_snippet, match_text, after_snippet)` fingerprint. Both the admin page AND the chapter render apply the filter, so excluded matches stop appearing in the prose too. Polymorphic by `target_type` so events / characters can adopt the same flow later.
5. **Polymorphic relationships.** `Url`, `TagAssociation`, and `MatchExclusion` use `(target_type, target_id)` pairs with no FK constraint on `target_id`; each first-class object has a `viewonly` SQLAlchemy relationship filtered to its own table name. Writes happen through the underlying rows directly (admin routes), not through the relationship.
6. **Audit columns.** `created_by` + `last_edited_by` columns sit on every `AbstractObject` row plus `TagAssociation`. ORM `before_insert` / `before_update` hooks (in `app/models/audit.py`) stamp the current Flask-Login user's username (or `'rotk.net_system'` outside a request).
7. **Edit log.** Every admin save also writes an `Edit` row with the model name + row id + a JSON diff of changed fields. Visible at `/admin/edits`.

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
2. Drop a `docker-compose.override.yml` on the VPS that deletes the bundled `db`, joins the `shared` network, and points `POSTGRES_HOST=postgres`.
3. Add a site block to the boilerplate's `caddy/Caddyfile` reverse-proxying the app container.
4. Run the data-population CLI commands once.

Full walkthrough in `README.md`.

## CLI commands (defined in `rotk.py`)

| Command | What it does |
|---|---|
| `flask create-all` | `db.create_all()` — create schema |
| `flask apply-migrations` | Run new `migrations/*.sql` files (tracked in `_schema_migrations`). Each file should be idempotent (`IF NOT EXISTS` / `IF EXISTS`); already-applied files are skipped. |
| `flask scrape-book` | Pull all 120 chapters from threekingdoms.com (INSERT only — skips chapters already in the DB). |
| `flask rescrape-chapter <num>` | Re-fetch ONE chapter and UPDATE its row in place. Safe — never touches chapter_character / chapter_location / event_chapter / MatchExclusion. Use after a scraper fix. |
| `flask rescrape-all-chapters` | Same as above but loops every chapter in the DB. ~120 HTTP fetches; idempotent (prints `unchanged` when source matches). |
| `flask scrape-characters` | Pull characters from Wikipedia A–Z pages, populate factions + roles |
| `flask build-chapter-character-association` | Populate the chapter_character join table by regex-scanning each chapter; needs to run after scrape-* |
| `flask build-location-chapter-association` | Same shape but for the chapter_location M2M — populates `Chapter.locations` (membership only, doesn't touch per-(chapter, location) `keywords` overrides). Skips soft-deleted Locations. Idempotent. |
| `flask recount-book-mentions` | Recompute `Character.book_mention_count` across the whole book. Run after scraping new chapters or alias changes. |
| `flask assign-default-portraits` | For characters with images but none visible, promote one to default (auto-makes visible). Prefers a configurable tag; random fallback. |
| `flask scrape-koei-images` | Scrape character portraits from koei.fandom.com into `app/static/portraits/` + `Portrait` rows |
| `flask randomize-faction-colours` | Randomize bg/font/border on every faction; font chosen for WCAG-readable contrast |
| `flask randomize-role-colours` | Same as `randomize-faction-colours` but for `Role` rows |
| `flask seed-location-types` | Insert the standard `LocationType` rows (Province, Commandery, County, City, Settlement, Pass, Landmark, Building, Mountain, River, Battlefield) — idempotent |
| `flask import-admin-divisions [PATH] [--dry-run]` | Walk a Province/Commandery/County/City CSV (default `data/3k_admin_divisions.csv`) and create the corresponding `Location` rows with `parent_id` + `location_type_id` wired. Idempotent: matches by English name first, Chinese name second; fills in NULL fields on existing rows but never overwrites values already set. |
| `flask make-admin EMAIL` | Promote a user to admin (also marks them confirmed) |
| `flask create-user EMAIL USERNAME [--admin]` | Create a user directly; prompts for the password |
| `flask dump-chapter-triage N` | Dump every tagged character/location/event match in chapter N (with snippet, via, full disambiguation facts — courtesy names, dates, ancestral home, roles, factions, chapter list, URLs — and same-needle candidates carrying the same facts) as JSON to stdout. Read-only — for piping into an LLM triage pass. |
| `flask apply-triage-decisions FILE [--apply]` | Batch-apply triage decisions (`exclude` / `restore` / `remove_m2m`) from a JSON file. Default is dry-run; pass `--apply` to write. Removal-class actions trigger a stronger y/N confirm. Idempotent. |
| `flask dump-chapters-for-dating START [END]` | Dump chapter prose + dated context (tagged characters/events with known dates, neighboring chapter names) as a JSON array on stdout. For LLM-assisted chapter dating — pipe to a file. Read-only. |
| `flask apply-chapter-dates FILE [--apply]` | Apply `[{chapter_num, date, _note?}]` JSON to `chapter.date`. Dry-run by default; `--apply` writes. Idempotent (no-ops for unchanged rows). Audit columns + Edit log are stamped automatically. |
| `flask apply-chapter-character-summaries FILE [--apply]` | Apply `[{chapter_num, character_id, summary, _note?}]` JSON to `chapter_character.summary`. Dry-run by default; `--apply` writes. Skips entries whose character isn't tagged in the chapter (won't auto-create associations — use the admin UI for that). Idempotent. |
| `flask dump-locations [--type Province\|Commandery\|...]` | Dump every active Location as a JSON array (id, name, chinese_name, type, parent_chain, lat/lng, has_geojson flag) on stdout. For LLM-assisted boundary sourcing on the /map view. Read-only. |
| `flask apply-location-geo FILE [--apply]` | Apply `[{id, latitude?, longitude?, geojson?, _note?}]` JSON to Location rows. Each entry must include a point and/or a Polygon/MultiPolygon GeoJSON geometry. Dry-run by default; `--apply` writes. Idempotent (no-ops for unchanged values). |
| `flask check-date-parsing [--only chapter\|event\|character]` | Sweep every free-form date string (chapter.date, event.date, character.birth_date/death_date) and print the ones `tools.date_parser` can't parse. Read-only — used to spot which strings need parser tweaks for the Timeline view. |
| `flask deploy` | No-op — `pass` in body (called by `boot.sh`) |

**When you add a new `@app.cli.command()`, also add it to this table AND to the matching table in `README.md`.** The README table is the one users see; this one is what future Claude sessions read first.

## Conventions worth knowing

- **Soft delete** via `is_deleted` on `AbstractObject`. Use `Model.get_all_active()` to filter.
- **Case-sensitive name matching** is intentional — `name`/`aliases` columns use the Postgres `C` collation (byte-wise comparison) so `Cao` and `cao` (and `ü` vs `u`) are distinct. The previous MySQL incarnation used `utf8mb4_bin` for the same effect. This is why `flask scrape-characters` lowercases roles but NOT factions.
- **`sort_order=-1` on `mapped_column`** is used to keep inherited columns to the left in the physical table layout.
- **Plain-SQL migrations.** Schema changes go into `migrations/NNNN_*.sql`, applied by `flask apply-migrations` (tracked in `_schema_migrations`). Each file must be idempotent (`IF NOT EXISTS` / `IF EXISTS` / `ON CONFLICT DO NOTHING` / `DO $$ ... $$`) so partial reruns are safe. Flask-Migrate / Alembic itself is intentionally not wired up — plain SQL is enough for a single-tenant single-author project and keeps the dependency surface small.
- **Admin gate** is `is_administrator` AND `confirmed` (both columns on `User`), enforced by `@admin_required`. First admin is bootstrapped via `flask make-admin <email>` or `flask create-user <email> <username> --admin`. After that the admin/users page promotes/demotes other users.
- **Email** is via Flask-Mail over SMTP. With no `MAIL_SERVER` configured, outbound mail is logged to stderr instead — dev works out of the box.
- **Polymorphic relationships** (`Url`, `TagAssociation`, `MatchExclusion`) use `target_type` (string) + `target_id` (no FK). Adding a new owner type means: (1) string the target_type allowlist in views, (2) add a viewonly `urls` / `tags` relationship to the model with `primaryjoin=and_(YourModel.id == foreign(Url.target_id), Url.target_type == 'yourtype')`, (3) wire the edit page partial. No migration needed.
- **Audit stamping is automatic** via ORM event hooks in `app/models/audit.py`. The hook detects column presence with `hasattr` — adding `created_by` / `last_edited_by` to a new model is a migration-only change, no decorator or call-site update.
- **Tag-style switcher targets `.text-ref` spans.** Character refs already carry it; events / locations don't (they keep a fixed black-underline style). To future-proof a new inline-ref type into the switcher, add the `text-ref` class + `data-bg` / `data-font` / `data-border` attributes in its `build_*_ref_html()`.
- **Match exclusion fingerprints** are computed against `strip_html_tags(chapter.content)` (not the raw HTML), so both the admin page and the chapter renderer must use the same trim algorithm. The chapter render counts per-(loc_id, needle) occurrences and consults a pre-computed skip-index set. Currently wired for `target_type='location'` only; events / characters can adopt the same flow.
- **Picker datalists** use `value="Name #<id>"` so duplicate-named rows still resolve unambiguously. `admin_picker.js` parses the id out and writes a sibling hidden field. Options can carry a `data-keywords` attribute (comma-delimited name + aliases) which `data-picker-keywords-target="<field_name>"` auto-fills into the keywords field — but only when that field is empty, so admin-typed values are never trampled.
- **`badge_widget` is the universal tag renderer.** Any `AbstractTag`-shaped object (Faction, Role, Tag, UrlType, EventType) renders the same way: three colours + optional Font Awesome icon prefix. Don't hand-roll `<span class="badge">` — use the macro so a new colour-locked column / icon column gets picked up everywhere automatically.

## Known landmines

See `ISSUES.md` for the full running list. Highlights still open:

- Character name fields are typo'd as `courtesty_name` (and `chinese_courtesty_name`) throughout models, forms, and templates. Renaming is a coordinated change (#19).
- Birth/death dates are stored as `String(N)` and can't be range-queried, though widening to fit BC years has shipped (#20).
- No tests yet — the inline-tagging regex pipeline in particular would benefit from a pytest harness (#25).

## Things to ask before doing

- **Don't run scrapers without confirming.** They hit external sites ~150 times and overwrite/duplicate rows depending on existing state. The current scraper has no upsert logic — re-running will throw IntegrityErrors on the unique constraint and skip rows.
- **Don't enable Flask-Migrate retroactively** without an Alembic baseline plan — `db.create_all()` (now followed by the SQL files in `migrations/`) is the source of truth, and a fresh Alembic autogenerate would not match.
- **The MySQL → Postgres migration** (May 2026) changed: the DB URL builder in `config.py`, the `collation` argument in `app/models/abstract.py` (`utf8mb4_bin` → `C`), the bundled `db` service in `docker-compose.yml` (mysql:8.4 → postgres:16-alpine), `.env.example` (`MYSQL_*` → `POSTGRES_*`), and the requirements (`mysqlclient` / `mysql-connector` → `psycopg[binary]`). The DB was renamed `rotk.net` → `rotk_net` (no dot) to avoid postgres quoting hassles. `docker-compose.prod.yml`, `docker-compose.ambrose.yml`, `db-init/`, and the `nginx/` config were deleted — production now uses `stateful_boilerplate` for TLS/proxy.

## Memory

The auto-memory store lives at `~/.claude/projects/-home-renton-Desktop-dev-codedev-webdev-rotk-net/memory/`. Use it for things that should persist across sessions (user preferences, project decisions). Don't store anything in memory that's already derivable from the code or git history.
