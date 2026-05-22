# Ambrose deployment (shared `stateful_boilerplate`)

Compose overlay for running `rotk.net` as a child of the shared
[`stateful_boilerplate`](../../../stateful_boilerplate) stack — shared Caddy,
Postgres, and Redis on a single VPS named `ambrose`.

This overlay sits on top of the base `docker-compose.yml`. Among other things
it:

- Drops the bundled `db` service (`db: !reset null`) so rotk uses the shared
  postgres cluster instead.
- Strips the local source bind-mount (`volumes: !reset []`) so the running
  container is the image you built, not whatever happens to be on disk.
- Removes the published host port (`ports: !reset []`) — Caddy reaches us
  over the shared docker network.
- Switches `FLASK_ENV=production` and points `POSTGRES_HOST=postgres`.

> **Why isn't this at the repo root?** Docker-compose auto-applies any
> `docker-compose.override.yml` it finds in the working directory. If this
> overlay lived at the repo root it would silently activate on every
> developer's laptop — strip their bind-mount, and edits to templates / code
> would stop reaching the container until a rebuild. Keeping it under
> `examples/` means it only applies when you opt in with `-f`.

## Prerequisites

- A VPS already running `stateful_boilerplate` (Caddy + shared Postgres + Redis).
- A postgres role + DB carved out on the shared cluster (one-off; see the
  main README for the SQL).
- A Caddy site block in `stateful_boilerplate/caddy/Caddyfile` reverse-proxying
  to the `rotk-app` container.

## Bring it up

```bash
cd /opt/rotk.net

docker-compose \
  -f docker-compose.yml \
  -f examples/ambrose/docker-compose.override.yml \
  up -d --build
```

To avoid typing both `-f` flags each time, set this in `/opt/rotk.net/.env`:

```bash
COMPOSE_FILE=docker-compose.yml:examples/ambrose/docker-compose.override.yml
```

Then plain `docker-compose ...` includes both files.

## Migrating from a root-level override

If you deployed before this overlay was moved, the VPS will still have a
tracked `docker-compose.override.yml` in the repo root that goes away on the
next `git pull`. After pulling, switch the deploy command to use `-f` (or
set `COMPOSE_FILE` as above) and rebuild:

```bash
cd /opt/rotk.net
git pull
docker-compose \
  -f docker-compose.yml \
  -f examples/ambrose/docker-compose.override.yml \
  up -d --build
```
