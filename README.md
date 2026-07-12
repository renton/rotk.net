# rotk.net

An annotated, browsable web edition of **Romance of the Three Kingdoms** by Luo Guanzhong (Brewitt-Taylor translation, Khang Nguyen edition). Each chapter is rendered with inline character "tags" — click a name in the prose to see who they are, which faction they served, and their role in the war.

Live at [rotk.net](https://rotk.net).

## Features

- **Annotated chapters** — all 120 chapters with inline character / event / location tagging, per-chapter mention counts, and a sidebar with character panels (portraits, roles, factions, external links).
- **Per-paragraph annotations** — public reader notes plus private admin threads, anchored to paragraph content.
- **Yearly territory maps** — chapters dated to a year (or span) show a collapsible map panel: one tab per year with an uploaded territory map, a drag-to-pan / wheel-to-zoom viewer, and the factions present that year with click-through leader panels. Curated at `/admin/yearly-maps`.
- **Factions with leaders** — factions carry admin-curated leader characters, shown as pills on the factions list and in the map panels.
- **Map + timeline views** — locations plotted on an interactive map (pins + GeoJSON territories); events and chapters on a parsed-date timeline.
- **Character explorer** — filter by faction / role / letter / search, sortable by book-wide mention count; every character has a public detail page (portraits, roles, factions, relationships, chapter appearances) reachable from any pill on the site.
- **Admin suite** — association editors with per-snippet match exclusions, chapter prose hiding, an image manager, audit trail of every edit, and an in-app how-to FAQ.
- **Public JSON API** — read-only `/api/v1` with rich joined payloads for every public resource (characters, factions, events, locations, chapters incl. prose, relationships, year maps, public annotations), self-describing index, and an admin API Explorer for trying endpoints.

## Stack

- Python 3.12, Flask 3.1, SQLAlchemy 2.0
- PostgreSQL 16 (via the bundled `db` service for local dev, or a shared cluster in production)
- Bootstrap-Flask + Bootstrap 5 (CDN), server-rendered Jinja2 templates
- gunicorn behind a reverse proxy in production (Caddy in both supported deployment paths)
- Docker + docker-compose

## Deployment paths

The app supports two production paths:

1. **[Standalone](examples/standalone/README.md)** — run rotk.net on its own VPS with a bundled Caddy for auto-TLS. The base `docker-compose.yml` plus the overlay in `examples/standalone/` is everything you need.
2. **[Shared boilerplate](#production-deployment-via-stateful_boilerplate)** — drop rotk.net into a VPS already running [`stateful_boilerplate`](../stateful_boilerplate) (shared Caddy + Postgres + Redis). For when you're hosting several stateful apps on the same host.

Both keep the base `docker-compose.yml` intact and use compose overrides to swap the moving parts. Pick whichever fits your hosting story.

## Quick start (development)

```bash
cp .env.example .env
# Edit .env and set:
#   SECRET_KEY (any long random string)
#   POSTGRES_PASSWORD (any value — local dev only)
```

Bring it up:

```bash
docker-compose up
```

The bundled postgres container initialises with the role/DB named in `.env` (defaults: user `rotk_app`, DB `rotk_net`) on first boot. The Flask app connects as that role.

Then populate the empty DB — see [Populating the data](#populating-the-data) below.

---

## Populating the data

After first boot the database is empty. The app needs a handful of commands to fill in the schema and pull the source content. Run them **in order** — later commands depend on rows that earlier commands insert.

> Compose v2 users (most installs these days) should substitute `docker compose` (space) for `docker-compose` (hyphen). Same commands, same arguments.

```bash
# 1. Create the tables from the current SQLAlchemy models. Idempotent.
docker-compose exec app flask create-all

# 2. Apply every SQL file in migrations/ that hasn't run yet (tracked in
#    the _schema_migrations table). Idempotent — re-runnable any time.
docker-compose exec app flask apply-migrations

# 3. Scrape all 120 chapter texts from threekingdoms.com (~120 fetches).
docker-compose exec app flask scrape-book

# 4. Scrape the Wikipedia character index pages (~26 fetches). Populates
#    `character`, `faction`, and `role`.
docker-compose exec app flask scrape-characters

# 5. Build the chapter↔character association cache. Required for the
#    chapter view sidebar to work.
docker-compose exec app flask build-chapter-character-association
```

After step 5 finishes, visit `http://localhost/` for the table of contents.

**Optional — seed the Location hierarchy from the bundled CSV** so chapter sidebars and the `/locations` page show admin-division ancestry:

```bash
# 6. Seed the standard LocationType rows (Province, Commandery, County, City, ...).
docker-compose exec app flask seed-location-types

# 7. Import the Province/Commandery/County hierarchy from data/3k_admin_divisions.csv.
#    Adds ~800 locations with parent_id + location_type_id wired. Idempotent.
docker-compose exec app flask import-admin-divisions

# 8. Build the chapter↔location association cache (mirror of step 5 for locations).
docker-compose exec app flask build-location-chapter-association
```

### Re-running individual jobs

* **`scrape-book`** — re-running adds duplicate chapter rows (it does not upsert). If you need to refresh chapter content, drop the table first or DELETE from it.
* **`scrape-characters`** — same caveat. The dedup is via DB unique constraints, so re-runs are mostly a no-op for already-known characters but will log "Duplicate key" warnings for each.
* **`build-chapter-character-association`** — **idempotent**. Clears the join table for each chapter before refilling, so re-run any time you've added new characters or chapters and want the chapter view to pick them up.

### Creating the first admin

Users register through `/auth/register`. The first admin needs to be promoted from the command line:

```bash
docker-compose exec app flask make-admin you@example.com
```

You can also create a user directly (handy if SMTP isn't set up yet and you just want to log in):

```bash
docker-compose exec app flask create-user you@example.com you --admin
# prompts for password
```

After that, additional admins can be promoted via the **Users** page in the navbar dropdown (visible only to confirmed admins).

### Sending email

The auth flow sends confirmation and password-reset emails. Set the `MAIL_*` variables in `.env` to any SMTP provider — see `.env.example` for Mailgun/SendGrid/SES/Gmail examples. If `MAIL_SERVER` is left blank, outbound mail is suppressed and each message body is logged to stderr instead, which is enough for local dev.

---

## CLI commands

Defined in `rotk.py`. Run inside the app container with `docker-compose exec app flask <cmd>`.

| Command | Purpose |
|---|---|
| `create-all` | Run `db.create_all()` to create all tables from the current model definitions |
| `apply-migrations` | Apply any unapplied `migrations/*.sql` files in lexicographic order; tracks applied filenames in `_schema_migrations`. Idempotent. |
| `scrape-book` | Fetch all 120 chapters from `threekingdoms.com` into the `chapter` table (INSERT only — skips chapters already in the DB) |
| `rescrape-chapter <num>` | Re-fetch one chapter and UPDATE its row in place. Never touches associations or per-snippet exclusions — use this after a scraper fix |
| `rescrape-all-chapters` | Loop `rescrape-chapter` across every chapter currently in the DB. Idempotent (prints `unchanged` when source matches) |
| `scrape-characters` | Fetch character index pages from Wikipedia and populate `character`, `faction`, `role` |
| `build-chapter-character-association` | Regex-scan each chapter and populate the `chapter_character` join table; chapter view uses this cache when present |
| `build-location-chapter-association` | Same idea for the `chapter_location` M2M — populates `Chapter.locations` from each location's name + aliases. Idempotent. Skips soft-deleted Locations. |
| `recount-book-mentions` | Recompute `Character.book_mention_count` (association-aware — only counts mentions in chapters the character is linked to via `chapter_character`, using per-chapter keywords with fallback to global aliases). Fires automatically on association add/remove/switch, edit-character label change, and rescrape; this CLI is the bulk one-shot for cases where the auto-triggers weren't in place (e.g. pre-`cdb3180` prod data). |
| `backfill-association-keywords [--dry-run]` | One-shot seed of `chapter_character.keywords` / `event_chapter.keywords` / `chapter_location.keywords` from each entity's `name + aliases` (whitespace-stripped, deduped). Run after applying migration 0012 to move existing associations into the per-chapter keyword model. Idempotent — only touches rows still on the empty default. |
| `clean-empty-location-geojson [--dry-run]` | Scrub `Location.geojson` rows that hold non-object JSON (usually the JSON string `""` from a pre-`11f25f9` `new_location` bug). Real Polygon/MultiPolygon objects are left alone; anything else is reset to NULL. |
| `backfill-annotation-refs [--dry-run]` | Attach auto-detected character/location references to annotations created before migration 0016. Skips annotations that already have refs — it never refreshes existing ones (see the note under Features → Annotations). Idempotent. |
| `assign-default-portraits [--preferred-tag 1MROTK] [--seed N] [--dry-run]` | For each character that has portraits but none visible, promote one to default (which also makes it visible). Prefers portraits tagged with `--preferred-tag`; falls back to a random pick. |
| `scrape-koei-images [--character-id N] [--skip-existing/--refresh] [--limit N] [--max-per-character 200] [--delay 0.5]` | Scrape **all** Koei portraits per character (filename starting with the character's name). Downloads to `app/static/portraits/`, creates a `Portrait` row per image, auto-creates a `Tag` from each filename's variant code (e.g. `DW9` from `Cao Cao (DW9).png`) and attaches it. De-duplicates by `image_url` across runs. |
| `randomize-faction-colours [--faction-id N] [--seed N] [--dry-run]` | Assign each faction a new random `bg_colour` / `font_colour` / `border_colour`. Font colour is chosen for WCAG-readable contrast against the background. |
| `randomize-role-colours [--role-id N] [--seed N] [--dry-run]` | Same as `randomize-faction-colours` but for `Role` rows. |
| `seed-location-types` | Insert the standard `LocationType` rows (Province, Commandery, County, City, Settlement, Pass, Landmark, Building, Mountain, River, Battlefield). Idempotent — skips any already present. |
| `import-admin-divisions [PATH] [--dry-run]` | Import the Province/Commandery/County/City hierarchy from a CSV (default `data/3k_admin_divisions.csv`). Inserts as "X Province" / "X Commandery" / "X County" with `parent_id` wired up; column-4 entries keep their raw cell name. Idempotent — existing rows matched by English or Chinese name are reused, with their `parent_id` / `location_type_id` filled in if currently NULL. |
| `make-admin EMAIL` | Promote the user with the given email to administrator (also marks them confirmed) |
| `create-user EMAIL USERNAME [--admin]` | Create a new user directly; prompts for the password |
| `check-date-parsing [--only chapter\|event\|character]` | Print every free-form date string the timeline parser can't read, grouped by source. Read-only — used to find which strings need parser tweaks. |
| `dump-chapters-for-dating START [END]` | Dump chapter prose + dated context (tagged characters/events with known dates, neighboring chapter names) as JSON on stdout. Read-only — feeds an LLM-assisted chapter dating workflow. |
| `apply-chapter-dates FILE [--apply]` | Apply `[{chapter_num, date, _note?}]` JSON to `chapter.date`. Dry-run by default; `--apply` writes. Idempotent. |
| `apply-chapter-character-summaries FILE [--apply]` | Apply `[{chapter_num, character_id, summary, _note?}]` JSON to `chapter_character.summary`. Dry-run by default; `--apply` writes. Skips entries whose character isn't tagged in the chapter. Idempotent. |
| `dump-locations [--type ...]` | Dump every active Location as JSON on stdout (id, name, chinese_name, type, parent_chain, lat/lng, has_geojson). Read-only — feeds the boundary-sourcing workflow for the /map view. |
| `apply-location-geo FILE [--apply]` | Apply `[{id, latitude?, longitude?, geojson?, _note?}]` JSON to Location rows. Each entry must include a point and/or a Polygon/MultiPolygon GeoJSON. Dry-run by default; `--apply` writes. Idempotent. |
| `apply-fixes FILE [--apply]` | Generalized cross-resource bulk fixes from a JSON op list: `update` fields on any resource, `add/remove_relationship`, `add/update/remove_association` (chapter links + keywords/summary), `add/remove_faction_leader`. Dry-run by default; `--apply` writes (removals get a stronger confirm). Idempotent; audit + Edit log stamped automatically; affected characters get mention recounts. Fix files live in `data/fixes/`. |
| `deploy` | No-op; called automatically by `boot.sh` on container start |

---

## Standalone production deployment

Self-host on a single VPS with no extra infrastructure. The base compose plus the overlay in `examples/standalone/` adds a Caddy reverse proxy with auto-TLS via Let's Encrypt.

See [`examples/standalone/README.md`](examples/standalone/README.md) for the full walkthrough. The short version:

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY, POSTGRES_PASSWORD, MAIL_* (or leave blank),
# plus DOMAIN and CADDY_EMAIL for the Caddy overlay.

docker-compose \
  -f docker-compose.yml \
  -f examples/standalone/docker-compose.tls.yml \
  up -d --build
```

Then run the four data-population commands (see [Populating the data](#populating-the-data)).

---

## Production deployment via `stateful_boilerplate`

If you're already running [`stateful_boilerplate`](../stateful_boilerplate) (shared Caddy + Postgres + Redis on one VPS), drop rotk.net in as a child project. rotk.net's base compose is shipped as-is, and a `docker-compose.override.yml` on the VPS swaps the bundled `db` service for the shared postgres cluster and joins the `shared` docker network so Caddy can reach it.

The full walkthrough is in `stateful_boilerplate/USAGE_GUIDE.md`. Specifically for rotk.net:

**1. Carve out the role + DB on the shared cluster** (one-off, on the VPS):

```bash
cd ~/stateful_boilerplate
ROTK_DB_PASSWORD="$(openssl rand -base64 24)"
echo "SAVE THIS: $ROTK_DB_PASSWORD"

docker compose exec -T postgres psql -U postgres <<SQL
CREATE ROLE rotk_app WITH LOGIN PASSWORD '${ROTK_DB_PASSWORD}';
CREATE DATABASE rotk_net OWNER rotk_app;
SQL
```

**2. Deploy the code to the VPS** (e.g. `/opt/rotk.net`).

**3. Write `/opt/rotk.net/docker-compose.override.yml`:**

```yaml
services:
  db: !reset null

  app:
    container_name: rotk-app
    restart: unless-stopped
    depends_on: !reset []
    ports: !reset []
    environment:
      FLASK_ENV: production
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_USER: rotk_app
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: rotk_net
      # Point rate-limiting at the boilerplate's shared redis so limits
      # are global across all gunicorn workers (not per-worker).
      RATELIMIT_STORAGE_URI: "redis://:${REDIS_PASSWORD}@redis:6379/0"
    networks:
      - vswitch0
      - shared

networks:
  shared:
    name: shared
    external: true
```

**4. Write `/opt/rotk.net/.env`:**

```bash
FLASK_APP=rotk.py
SECRET_KEY=<paste new strong secret>

# Used by the override to wire the app to shared postgres.
POSTGRES_PASSWORD=<the value you saved in step 1>

# Same value as REDIS_PASSWORD in ~/stateful_boilerplate/.env. The
# override's RATELIMIT_STORAGE_URI substitutes this in to authenticate
# against the shared redis (which is --requirepass-protected).
REDIS_PASSWORD=<copy from boilerplate .env>

# Mail config (or leave blank to suppress sends).
MAIL_SERVER=...
APP_BASE_URL=https://rotk.net
```

**5. Add the Caddy route** in `~/stateful_boilerplate/caddy/Caddyfile`:

```caddy
rotk.net, www.rotk.net {
    import security_headers
    import rate_limit_default
    reverse_proxy rotk-app:8081
}
```

**6. Reload Caddy and bring up the app:**

```bash
cd ~/stateful_boilerplate && ./scripts/reload-caddy.sh
cd /opt/rotk.net && docker compose up -d --build
```

**7. Run data population against the shared DB** (same four steps as local dev — see [Populating the data](#populating-the-data) — just `docker compose` instead of `docker-compose`):

```bash
cd /opt/rotk.net
docker compose exec app flask create-all
docker compose exec app flask scrape-book
docker compose exec app flask scrape-characters
docker compose exec app flask build-chapter-character-association
```

---

## Project layout

```
rotk.py                  Application entry + CLI commands
config.py                Config classes (Development, Production)
boot.sh                  Container entrypoint (runs flask run in dev, gunicorn in prod)
Dockerfile               Python 3.12-slim image; installs requirements, runs boot.sh
docker-compose.yml       Base: app + postgres. Overlaid by examples/standalone/ or by a VPS-side override for stateful_boilerplate.

app/
  __init__.py            Flask app factory; extensions; blueprint registration
  models/                SQLAlchemy models (Character, Chapter, Faction, Role, User, ...)
  blueprints/main/       Public routes: TOC, chapter view, character/faction/role listings + admin edits
  blueprints/auth/       Login, register, confirm, forgot/reset password, change password/email
  blueprints/admin/      Admin-only routes (user listing, promote/demote)
  templates/             Jinja2 templates
  static/                styles.css, favicon, placeholder portrait, chapter.js

tools/
  scraper.py             Web scrapers for the book text and character index
  book_parser.py         Inline character-tagging regex pipeline (now also tags events + locations, with per-snippet exclusions)
  colours.py             HSL palette generator used by the randomize-colour CLI and the in-form Randomize buttons
  favicon_fetcher.py     Auto-fetch favicons for any URL added to a Character / Event / Location / Faction / Role
  dbm.py                 Generic DB helper class
  validators.py          Hex-colour validator for faction/role badges
  decorators.py          @admin_required decorator

examples/
  standalone/            Compose overlay + Caddyfile for self-hosting on one VPS
```

## Features

### Reader-facing
- **Table of contents** at `/` listing all 120 chapters
- **Chapter view** at `/chapter/<n>` rendering the chapter text with inline tags for three kinds of references:
  - Character badges — coloured pills tied to the character's primary faction
  - Event refs — black-underlined; click to open the sidebar's *Events* accordion and highlight the matching row
  - Location refs — same behaviour as events, scoped to the *Locations* accordion
- **Tag style switcher** on every chapter page — choose how the inline character refs render (pills, squares, underlined, coloured-only). Persisted in `localStorage`.
- **Link style switcher** on every chapter page (desktop only) — *Click* (default) or *Hover* to populate the sidebar's character info panel. Persisted in a cookie.
- **Chapter sidebar accordion** with:
  - *Character Info* — portrait gallery, mention counts, role + faction badges, attached URLs, optional admin-only *Edit* button
  - *Chapter Characters* — clickable list of every character associated with the chapter
  - *Events* — name + Event Type badge + location + URLs
  - *Locations* — name + lat/lng + URLs
- **Character browser** at `/characters` with alphabet tabs, search, and two independent faction filters (primary / past)
- **Faction, Role, Event, Location pages** with their own list views, admin-gated edit buttons, and faction-filter shortcuts wired into the character browser
- **User accounts** — `/auth/register`, `/auth/login`, `/auth/forgot-password`, `/auth/change-password`, `/auth/change-email`, all with email confirmation.

### First-class content types (admin)
- **Character** (incl. portraits, roles, primary + past factions)
- **Faction** — coloured tag, randomize-palette button, merge into another faction (carries M2M membership), hide flag
- **Role** — coloured tag mirroring Faction
- **Tag** — coloured tag, attachable to portraits and other things via polymorphic `TagAssociation`
- **Event** — name, aliases, optional `Location` FK, optional `EventType` FK, geo-point override, hide-on-map flag
- **Location** — name, aliases, lat/lng
- **URL** — polymorphic external link attachable to any of the above; auto-fetched favicon; categorised by `UrlType`
- **UrlType** — coloured tag with a Font Awesome icon class; renders as the badge prefix in URL lists
- **EventType** — coloured tag with a Font Awesome icon class; shows next to each event in the chapter sidebar
- **MatchExclusion** — per-snippet "don't inline-tag this match" record (wired for Character + Location associations)
- **ChapterHiddenSnippet** — admin-hidden prose span; removed from the public chapter render entirely (fingerprinted like MatchExclusion)
- **Annotation** — per-paragraph threaded note, public (any reader) or private (admins only), with auto-detected character/location references
- **Edit log** — every admin save is recorded (model, row, field-by-field diff, who, when) and viewable at `/admin/edits`
- **Audit stamps** — every first-class row gets `created_by` and `last_edited_by` columns via ORM event hooks

### Annotations
- Threaded notes attached to a chapter paragraph. Public annotations show a black notepad icon to all readers (click = read-only thread modal); private annotations show a red icon + exclamation to admins only.
- Admins hover any paragraph to get a blue "add" icon; the modal thread supports add (private by default), per-entry soft-delete, and restore.
- Character/location references are **auto-detected at create time** from the chapter's associations and stored on M2M tables. **Known + accepted limitation:** if an association (or its keywords) is added to a chapter *after* an annotation already exists on a paragraph mentioning it, the annotation's refs are not retroactively updated — preferable for now since annotations may later gain manual/richer character-location selection. `flask backfill-annotation-refs` only fills annotations with no refs at all.
- Admin list pages (`/admin/annotations/public`, `/admin/annotations/private`) stack annotations one row per thread with count, first-note preview, character pills + location links (each linking to the chapter's association editor), chapter deep-link (new tab, anchored to the paragraph), filters by chapter / character / location, and a soft-deleted-only view. The private list has a **Close** button that resolves a whole thread ticket-style.

### Admin tools
- `/admin/faq` — how-to reference for every common task (linked from the admin dropdown)
- `/admin/chapter-associations`, `/admin/event-associations`, `/admin/location-associations` — pick a chapter, see what's associated, add/switch/remove. The picker auto-fills the *Keywords* field with `name, aliases…` when you commit a selection.
- Per-snippet match exclusions on Character + Location associations (red × on each snippet; restore from the *Excluded snippets* fold; AJAX, no reload)
- `/admin/chapter-edit` — highlight prose and hide it from the public chapter view (strikethrough in the editor, absent from the public page; click to restore). Content itself is never editable.
- `/admin/annotations/public`, `/admin/annotations/private` — see Annotations above
- `/admin/duplicates` — character rows with name collisions
- `/admin/edits` — full edit history (filterable by model + row)
- `/admin/image-manager`, `/admin/tags`, `/admin/url-types`, `/admin/event-types` — CRUD for each tag-shaped type, with usage counts and reassign-before-delete guards
- `/admin/users` — promote / demote (you can't demote yourself or the last remaining admin)

## Public API

A read-only JSON API mirrors the public site at `/api/v1` — anonymous,
rate-limited (120 req/min per IP), GET-only. `GET /api/v1/` returns a
self-describing index of every endpoint and its query params (the same
registry that powers the admin API Explorer at `/admin/api-explorer`).

Lists are paginated (`?page`, `?per_page`, cap 100) and return
`{items, page, per_page, pages, total}`; detail endpoints return the
bare object. Payloads join related records in: a character carries its
factions, roles, relationships (sex-resolved labels), portraits, links
and chapter appearances; an event carries its sided faction lists;
chapters include the full prose.

```bash
curl -s https://rotk.net/api/v1/ | jq '.endpoints[].path'
curl -s 'https://rotk.net/api/v1/characters?q=Cao&sort=mentions&dir=desc' | jq '.items[0]'
curl -s https://rotk.net/api/v1/chapters/60 | jq '.title, .years'
curl -s 'https://rotk.net/api/v1/events?chapter_num=60' | jq '.items[].name'
```

Resources: `characters`, `factions`, `roles`, `tags`, `events`,
`event-types`, `locations`, `location-types`, `chapters` (by
`chapter_num`), `relationships`, `relationship-types`, `year-maps` (by
`year`), `annotations` (public threads only).

Admin data is not part of the API: there are no users/edits endpoints,
audit columns and notes are never serialized, and private annotations
are never served. The API is structurally read-only — a blueprint-level
guard rejects every non-GET method.

### MCP server

`mcp_server/rotk_mcp.py` wraps the API as [MCP](https://modelcontextprotocol.io)
tools so AI assistants can query the data directly — built mainly for
data-quality auditing (`rotk_find_data_gaps` sweeps for characters
without factions, unparseable dates, geo-less locations, …). Zero
dependencies beyond Python + `requests`; the repo-root `.mcp.json`
wires it into Claude Code sessions automatically. `ROTK_API_BASE`
selects the target site (default `https://rotk.net`). See
`mcp_server/README.md`.

## Running the tests

A ~600-test pytest suite lives in `tests/` (unit + route + composite
scenarios). It runs against a **dedicated `rotk_net_test` database** —
never the live one:

- `TestingConfig` (config.py) hardcodes the test DB name; it is never
  derived from `POSTGRES_DB`.
- `tests/conftest.py` refuses to run (hard `pytest.exit`) unless the
  resolved DB name ends in `_test`, and creates the DB on demand.
- **Shared-cluster note (ambrose):** `rotk_app` can't create databases
  on the shared postgres, so the test DB needs a one-time creation as
  the superuser — after which the conftest finds it and never asks again:

  ```bash
  cd ~/stateful_boilerplate
  docker compose exec -T postgres psql -U postgres \
    -c "CREATE DATABASE rotk_net_test OWNER rotk_app;"
  ```
- Every test runs inside a savepoint transaction that's rolled back,
  so tests are isolated from each other and nothing persists.

Run inside the app container (after a one-time `docker compose build app`
to pick up the pytest dependency):

```bash
docker compose exec app pytest -q            # full suite
docker compose exec app pytest tests/test_needle_pattern.py -q   # one file
docker compose exec app pytest -k lady_cao -q                    # by keyword
```

The pure-function suites (`test_needle_pattern`, `test_ref_builders`,
`test_annotation_canonical`, `test_hidden_snippets_pure`) don't touch
the DB and run in a couple of seconds. Scraper commands are
deliberately untested (network).

## Ops runbook

Common developer flows on the deployed instance (ambrose). All commands assume `cd ~/projects/rotk.net`.

### After a scraper fix — refresh chapter prose without losing admin work

`rescrape-chapter` and `rescrape-all-chapters` update `chapter.name` + `chapter.content` in place. The chapter row's `id` stays the same, so **every FK-referencing row survives**: `chapter_character` (and its per-chapter `keywords`), `event_chapter`, `chapter_location`, `match_exclusion`, `Edit` log entries. Book-mention counts are auto-recounted for affected characters.

```bash
git pull
docker compose exec app flask apply-migrations       # if new SQL files landed
docker compose restart app                           # if Python changed
docker compose exec app flask rescrape-chapter 29    # single chapter
# or:
docker compose exec app flask rescrape-all-chapters  # every chapter (skips unchanged)
```

**Never `DELETE FROM chapter WHERE ...` then re-scrape.** The FKs above all `ON DELETE CASCADE`, so a chapter delete wipes every association, keyword, and exclusion for that chapter.

**Caveat — MatchExclusion context shift.** Per-snippet exclusion rows are keyed by a fingerprint of the ~60 chars around each excluded match. When a rescrape inserts new prose inside that 60-char window, the stored fingerprint stops matching the regenerated one and the exclusion silently doesn't apply (the row is still there; it's just orphaned). Chapters recovered by the `class="2"` scraper fix in `f7a1ab5` are the ones most likely affected — spot-check chapters where you'd done a lot of × exclusions and re-flag any snippets that reappeared.

### After migration 0012 — seed per-association keywords

Migration 0012 added `keywords` columns to `chapter_character` / `event_chapter` / `chapter_location`. They start empty; the chapter renderer falls back to the entity's global aliases in that case, so nothing visibly breaks, but the per-chapter keyword model isn't in effect until seeded.

```bash
docker compose exec app flask apply-migrations
docker compose exec app flask backfill-association-keywords --dry-run   # preview
docker compose exec app flask backfill-association-keywords             # apply
```

Idempotent. Rows already populated (by admin edits on the association pages) are left alone.

### After the `Location.geojson = ""` bug fix — scrub legacy dirty rows

Pre-`11f25f9`, `new_location` wrote the raw form string into the JSONB column, so blank inputs stored the JSON scalar `""`. Downstream `has_geo` checks were fooled and the map blob got garbage. New-location and edit-location now write the validator's parsed value (dict or NULL), and `has_geo` checks are truthy (not `is not None`). Existing dirty rows need one scrub pass:

```bash
docker compose exec app flask clean-empty-location-geojson --dry-run
docker compose exec app flask clean-empty-location-geojson
```

Real Polygon/MultiPolygon rows are untouched.

### After editing many aliases or association keywords — force a full recount

Recount fanout is automatic on the trigger points listed under `recount-book-mentions` in the CLI table. Manual bulk recount is only needed for one-off catch-up (e.g. import from CSV, or the first apply of the association-aware formula on old data):

```bash
docker compose exec app flask recount-book-mentions
```

## Limitations and known issues

See [ISSUES.md](./ISSUES.md) for the running list of design notes. Highlights still relevant:

- "courtesty" is misspelled throughout (model fields, forms, templates) — coordinated rename pending
- No tests — pytest fixtures for the regex-tagging pipeline would catch a lot
- Plain-SQL migrations only; no Alembic. Fine for a single-author project, but a fresh contributor would need to read the `migrations/` directory rather than rely on auto-generated diffs.
