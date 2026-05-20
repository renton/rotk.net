# rotk.net

An annotated, browsable web edition of **Romance of the Three Kingdoms** by Luo Guanzhong (Brewitt-Taylor translation, Khang Nguyen edition). Each chapter is rendered with inline character "tags" — click a name in the prose to see who they are, which faction they served, and their role in the war.

Live at [rotk.net](https://rotk.net).

## Stack

- Python 3.12, Flask 3.1, SQLAlchemy 2.0
- MySQL 8.4
- Bootstrap-Flask + Bootstrap 5 (CDN), server-rendered Jinja2 templates
- gunicorn behind nginx, TLS via Let's Encrypt
- Docker + docker-compose

## Quick start (development)

```bash
cp .env.example .env
# Edit .env and set SECRET_KEY, MYSQL_ROOT_PASSWORD, MYSQL_APP_PASSWORD
```

Bring it up:

```bash
docker-compose up
```

The app is served at `http://localhost`. On first boot the database container runs `db-init/01-create-app-user.sh` which creates the `rotk.net` schema and a least-privileged `rotk_app` user. The Flask app connects as `rotk_app`. DDL commands need root, so populate the empty DB like this:

```bash
docker-compose exec -e MYSQL_USE_ROOT=1 app flask create-all
docker-compose exec app flask scrape-book          # ~120 chapter fetches from threekingdoms.com
docker-compose exec app flask scrape-characters    # ~26 alphabetised pages from Wikipedia
```

Then visit `http://localhost/` for the table of contents.

> **Note:** `Talisman(force_https=True)` is on unconditionally, so your browser may HSTS-upgrade `http://localhost` after the first visit. If you hit a redirect loop, use a fresh incognito window or clear HSTS for `localhost`.

### Creating an admin user

There is currently no registration view. Insert a user manually and flip `is_administrator`:

```bash
docker-compose exec db mysql -uroot -p rotk.net
```
```sql
INSERT INTO user (email, username, password_hash, confirmed, is_administrator)
VALUES ('you@example.com', 'you', '<werkzeug-hash>', 1, 1);
```

(Generate the hash with `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('yourpassword'))"`.)

## Production

```bash
docker-compose -f docker-compose.prod.yml up -d
```

The production compose adds an nginx reverse proxy that terminates TLS using certs mounted from the host's `/etc/letsencrypt/`.

### TLS / Let's Encrypt setup (host machine)

```bash
sudo apt install certbot
sudo certbot certonly --standalone -d rotk.net
# Certs land in /etc/letsencrypt/live/rotk.net/

# Auto-renew (certbot installs a systemd timer)
systemctl cat certbot.timer
sudo certbot renew --dry-run
```

To force a renewal:

```bash
sudo certbot renew --force-renewal
```

## CLI commands

Defined in `rotk.py`. Run inside the app container with `docker-compose exec app flask <cmd>`.

| Command | Purpose |
|---|---|
| `create-all` | Run `db.create_all()` to create all tables from the current model definitions |
| `scrape-book` | Fetch all 120 chapters from `threekingdoms.com` into the `chapter` table |
| `scrape-characters` | Fetch character index pages from Wikipedia and populate `character`, `faction`, `role` |
| `build-chapter-characters` | Debug helper — prints the characters found in chapter 1 |
| `deploy` | No-op; called automatically by `boot.sh` on container start |

## Project layout

```
rotk.py                  Application entry + CLI commands
config.py                Config classes (Development, Production)
boot.sh                  Container entrypoint (runs `flask deploy`, then gunicorn or flask run)
Dockerfile               Python 3.12 image; installs requirements, runs boot.sh
docker-compose.yml       Dev: app + mysql, port 80
docker-compose.prod.yml  Prod: app + mysql + nginx, port 80/443
nginx/nginx.conf         Reverse proxy + TLS termination

app/
  __init__.py            Flask app factory; extensions; blueprint registration
  models/                SQLAlchemy models (Character, Chapter, Faction, Role, User, ...)
  blueprints/main/       Public routes: TOC, chapter view, character/faction/role listings + admin edits
  blueprints/auth/       Login/logout (registration form exists but no view yet)
  templates/             Jinja2 templates
  static/                styles.css, favicon, placeholder portrait

tools/
  scraper.py             Web scrapers for the book text and character index
  book_parser.py         Inline character-tagging regex pipeline
  dbm.py                 Generic DB helper class
  validators.py          Hex-colour validator for faction/role badges
  decorators.py          @admin_required decorator
```

## Features

- **Table of contents** at `/` listing all 120 chapters
- **Chapter view** at `/chapter/<n>` rendering the chapter text with clickable character badges. Sidebar shows character details + faction colour-coding.
- **Character browser** at `/characters` with alphabet tabs, search, and faction/role filters (incl. "search past factions" toggle)
- **Faction and Role pages** at `/factions` and `/roles` showing each tag, its colour preview, and member count
- **Admin editing** for characters / factions / roles (auth-gated)
- **Login** at `/auth/login`

## Limitations and known issues

See [ISSUES.md](./ISSUES.md) for a detailed list. Highlights:

- `@admin_required` does not currently block anonymous users
- No Flask-Migrate / Alembic — schema changes require manual SQL or drop/recreate
- Character ↔ Chapter linking is recomputed by regex on every page view
- "courtesty" is misspelled throughout (model fields, forms, templates)
- No tests
