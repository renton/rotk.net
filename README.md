# rotk.net

An annotated, browsable web edition of **Romance of the Three Kingdoms** by Luo Guanzhong (Brewitt-Taylor translation, Khang Nguyen edition). Each chapter is rendered with inline character "tags" — click a name in the prose to see who they are, which faction they served, and their role in the war.

Live at [rotk.net](https://rotk.net).

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

After first boot the database is empty. The app needs four commands to fill in the schema and pull the source content. Run them **in order** — later commands depend on rows that earlier commands insert.

> Compose v2 users (most installs these days) should substitute `docker compose` (space) for `docker-compose` (hyphen). Same commands, same arguments.

```bash
# 1. Create the tables from the current SQLAlchemy models.
#    Idempotent; safe to re-run.
docker-compose exec app flask create-all

# 2. Scrape all 120 chapter texts from threekingdoms.com.
#    Hits the source site ~120 times; takes a few minutes.
docker-compose exec app flask scrape-book

# 3. Scrape character index pages from Wikipedia (26 alphabetised pages).
#    Populates `character`, `faction`, and `role` tables.
docker-compose exec app flask scrape-characters

# 4. Build the chapter↔character association cache.
#    Regex-scans each chapter for every character's names and aliases.
#    Required for the chapter view's sidebar to work.
docker-compose exec app flask build-chapter-character-association
```

After step 4 finishes, visit `http://localhost/` for the table of contents.

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
| `scrape-book` | Fetch all 120 chapters from `threekingdoms.com` into the `chapter` table |
| `scrape-characters` | Fetch character index pages from Wikipedia and populate `character`, `faction`, `role` |
| `build-chapter-character-association` | Regex-scan each chapter and populate the `chapter_character` join table; chapter view uses this cache when present |
| `scrape-koei-images [--character-id N] [--skip-existing/--refresh] [--limit N] [--delay 0.5]` | Scrape character portraits from `koei.fandom.com`, download to `app/static/portraits/`, and record one `Portrait` row per character. Skips characters that already have a Koei portrait by default; pass `--refresh` to re-scrape. |
| `randomize-faction-colours [--faction-id N] [--seed N] [--dry-run]` | Assign each faction a new random `bg_colour` / `font_colour` / `border_colour`. Font colour is chosen for WCAG-readable contrast against the background. |
| `make-admin EMAIL` | Promote the user with the given email to administrator (also marks them confirmed) |
| `create-user EMAIL USERNAME [--admin]` | Create a new user directly; prompts for the password |
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
  book_parser.py         Inline character-tagging regex pipeline
  dbm.py                 Generic DB helper class
  validators.py          Hex-colour validator for faction/role badges
  decorators.py          @admin_required decorator

examples/
  standalone/            Compose overlay + Caddyfile for self-hosting on one VPS
```

## Features

- **Table of contents** at `/` listing all 120 chapters
- **Chapter view** at `/chapter/<n>` rendering the chapter text with clickable character badges. Sidebar shows character details + faction colour-coding.
- **Character browser** at `/characters` with alphabet tabs, search, and faction/role filters (incl. "search past factions" toggle)
- **Faction and Role pages** at `/factions` and `/roles` showing each tag, its colour preview, and member count
- **User accounts** — `/auth/register`, `/auth/login`, `/auth/forgot-password`, `/auth/change-password`, `/auth/change-email`, all with email confirmation.
- **Admin panel** at `/admin/users` — confirmed admins can promote or demote any user (you can't demote yourself or the last remaining admin)
- **Admin editing** for characters / factions / roles (gated to confirmed admins)

## Limitations and known issues

See [ISSUES.md](./ISSUES.md) for the running list of design notes. Highlights still relevant:

- No Flask-Migrate / Alembic — schema changes require manual SQL or drop/recreate
- "courtesty" is misspelled throughout (model fields, forms, templates)
- No tests
