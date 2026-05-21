# Standalone production deployment

Deploy `rotk.net` on its own VPS — no `stateful_boilerplate`, no separate Caddy stack.

This directory layers a Caddy reverse proxy on top of the base `docker-compose.yml`. Caddy obtains a Let's Encrypt certificate automatically on first boot and proxies HTTPS traffic to the gunicorn app. The bundled `postgres` service from the base compose stays in place — that's where the data lives.

## Prerequisites

- A VPS reachable on ports 80 and 443.
- DNS A/AAAA records for your domain pointing at the VPS.
- Docker + docker-compose installed.

## Setup

```bash
# 1. Clone the repo onto the VPS.
git clone <your-fork> /opt/rotk.net
cd /opt/rotk.net

# 2. Create .env (use .env.example as a starting point).
cp .env.example .env
# Set SECRET_KEY, POSTGRES_PASSWORD, MAIL_* (or leave MAIL_SERVER blank
# to suppress sends), DOMAIN (the public hostname), CADDY_EMAIL (for
# Let's Encrypt's ACME account), and APP_BASE_URL (e.g. https://<domain>).
```

The two standalone-specific env vars not in the base `.env.example`:

```bash
# Hostname Caddy serves on. Must match a DNS record pointing at this host.
DOMAIN=rotk.example.com

# Email address used to register the Let's Encrypt account.
CADDY_EMAIL=you@example.com
```

```bash
# 3. Bring it up. The -f flags layer the standalone overlay on the base.
docker-compose \
  -f docker-compose.yml \
  -f examples/standalone/docker-compose.tls.yml \
  up -d --build

# 4. Populate the data (see the main README for context).
docker-compose -f docker-compose.yml -f examples/standalone/docker-compose.tls.yml \
  exec app flask create-all
docker-compose -f docker-compose.yml -f examples/standalone/docker-compose.tls.yml \
  exec app flask scrape-book
docker-compose -f docker-compose.yml -f examples/standalone/docker-compose.tls.yml \
  exec app flask scrape-characters
docker-compose -f docker-compose.yml -f examples/standalone/docker-compose.tls.yml \
  exec app flask build-chapter-character-association

# 5. Bootstrap the first admin.
docker-compose -f docker-compose.yml -f examples/standalone/docker-compose.tls.yml \
  exec app flask create-user you@example.com you --admin
```

Visiting `https://<DOMAIN>/` should show the table of contents.

## Tip: alias the compose invocation

Typing the two `-f` flags every time gets old:

```bash
export COMPOSE_FILE=docker-compose.yml:examples/standalone/docker-compose.tls.yml
# Now plain `docker-compose ...` includes both files.
```

(Or stick that line in `/opt/rotk.net/.env` — docker-compose reads it.)

## Customising

- **Don't want auto-TLS?** Replace the site block in `Caddyfile` with `:80 { reverse_proxy app:8081 }` and remove the `email` global.
- **Multiple domains?** Add them to the site address in `Caddyfile`, e.g. `rotk.example.com, www.rotk.example.com { ... }`. Caddy will issue a SAN cert covering both.
- **Already running another reverse proxy?** Skip Caddy entirely — point your existing proxy at the app container's port 8081 (gunicorn). You can drop this overlay and write a simpler one that just removes `ports:` from the base `app` service so it doesn't try to publish 80.
