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
    character.py         # Character, Link, Role, Faction, Portrait (+ association tables incl. faction_leader M2M — Faction.leaders, admin-curated on the faction edit page)
    chapter.py           # Chapter (name + content + chapter_num + M2M to Character / Event / Location)
    event.py             # Event (name, aliases, optional Location FK, optional EventType FK, geo override) + EventType (AbstractTag + factions1_label/factions2_label) + event_faction sided M2M (side 1|2 in PK; Event.factions1/.factions2 viewonly — writes hit the table directly)
    location.py          # Location (name, aliases, lat/lng) — chapter↔location M2M attached here
    tag.py               # Tag + TagAssociation (polymorphic by target_type + target_id)
    url.py               # Url + UrlType (polymorphic Url; FA-iconed UrlType)
    match_exclusion.py   # MatchExclusion — per-snippet "don't inline-tag this match" for a (chapter, target_type, target_id)
    chapter_hidden_snippet.py  # ChapterHiddenSnippet — admin-hidden prose spans (fingerprinted like MatchExclusion; removed from public render entirely)
    annotation.py        # Annotation (per-paragraph public/private threads, section_text content-addressed) + annotation_character / annotation_location M2Ms
    edit.py              # Edit (admin save audit log: model, row, field-by-field diffs)
    relationship.py      # RelationshipType (tag-shaped + side1_label/side2_label; blank side2 = symmetric) + Relationship (character1 IS the side-1 role; two-way by construction — both ends read the same row via describe_for)
    year_map.py          # YearMap — one territory-map image per year (184–280; `year` UNIQUE; files in static/yearmaps/; Portrait-style source_site/source_url credit pair; year_map_faction M2M = factions present that year, replaced wholesale on modal save)
    auth.py              # User, AnonymousUser, login_manager hooks
  blueprints/
    main/views.py        # Public + admin-edit routes for Character / Faction / Role / Event / Location;
                         #   chapter view (inline-tags characters + events + locations, applies per-snippet exclusions;
                         #   renders the yearly territory-maps panel from chapter.date); faction leader add/remove;
                         #   character relationship add/remove (sided rows — see relationship.py);
                         #   characters list sortable by book_mention_count (?sort=mentions&dir=asc|desc)
    main/forms.py        # EditCharacterForm, EditFactionForm, EditRoleForm, EditEventForm, EditLocationForm, AddUrlForm
    auth/views.py        # login, logout, register, confirm, forgot/reset password, change password/email
    auth/forms.py        # Login, Registration, ForgotPassword, ResetPassword, ChangePassword, ChangeEmail
    auth/emails.py       # send_email() helper (multipart .txt + .html; suppresses send when SMTP not configured)
    admin/views.py       # /admin/users, /admin/faq, /admin/duplicates, /admin/edits, /admin/tags,
                         #   /admin/url-types, /admin/event-types, /admin/image-manager,
                         #   /admin/chapter-associations, /admin/event-associations,
                         #   /admin/location-associations (+ per-snippet exclude / restore),
                         #   /admin/chapter-edit (+ hide / restore prose spans),
                         #   /admin/annotations/{public,private} (+ create / delete / restore / close-thread),
                         #   /admin/yearly-maps (+ per-year upload-or-edit modal incl. factions chip picker / remove),
                         #   /admin/relationship-types (+ new / edit / delete w/ in-use guard)
    admin/forms.py       # EditTagForm, EditUrlTypeForm, EditEventTypeForm, EditRelationshipTypeForm, CreateUserForm
  templates/             # Jinja2: book/, characters/, factions/, roles/, events/, locations/, admin/, auth/, errors/
                         # Shared partials: _macros.html (badge_widget with icon prefix),
                         #   _url_section.html (External Links fieldset on edit pages),
                         #   _url_list.html (read-only URL list w/ favicon + UrlType badge)
  static/
    styles.css           # Sidebar sticky rules, event/location ref styling, sidebar-flash animation
    js/                  # chapter.js (refs click + link-style cookie + accordion-flash),
                         #   chapter_style.js (tag-style switcher, localStorage-backed),
                         #   annotations.js (paragraph-thread modal, icon state updates, AJAX add/delete/restore),
                         #   admin_chapter_edit.js (highlight-and-hide prose spans),
                         #   admin_picker.js (datalist id resolver + auto-fill keywords field),
                         #   admin_confirm.js (data-confirm submit gate),
                         #   admin_colour_picker.js (Randomize palette button injector),
                         #   admin_yearly_maps.js (populate the shared Yearly Maps upload/edit modal per row),
                         #   image_panzoom.js (REUSABLE drag/wheel-zoom image viewer: Leaflet CRS.Simple on any
                         #     .image-panzoom[data-panzoom-src] element; auto-init + Bootstrap tab/collapse re-measure)

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
4. **Per-snippet exclusions** — admin can mark individual matches as bad on the three association editors (`/admin/chapter-associations`, `/admin/event-associations`, `/admin/location-associations`; character + location wired today, event structurally ready). Each exclusion stores a `(chapter, target_type, target_id, before_snippet, match_text, after_snippet)` fingerprint. Both the admin page AND the chapter render apply the filter, so excluded matches stop appearing in the prose too. The MatchExclusion table is polymorphic (`target_type` + `target_id`).
    - **Fingerprint, not offset, on purpose.** Positions in `chapter.content` shift whenever a paragraph is inserted anywhere upstream — a position-based exclusion would invalidate downstream rows on every rescrape. A content-addressed `(before, match, after)` triple survives content shifts as long as the surrounding ~60 chars of prose stay the same. The trade is that exclusions near a real content edit *can* orphan (their window's before/after string changed) — those need to be re-flagged via the admin UI.
5. **Per-(chapter, target) keywords** — the aliases used to inline-tag a character/event/location in a specific chapter live on the association row itself (`chapter_character.keywords`, `event_chapter.keywords`, `chapter_location.keywords`, added in migration 0012). Global `character.aliases` / `event.aliases` / `location.aliases` are the *fallback* when a per-chapter row's `keywords` column is empty (pre-backfill data). The rationale for moving from global to per-association: "resync should be per-chapter, not global" — an admin editing keywords on chapter 5 should only affect chapter 5's inline tagging, not every other chapter that also has that character. The three `chapter_associations_add` / `event_associations_add` / `location_associations_add` endpoints write to the association row's `keywords`; the global aliases are never touched by these forms. Backfill from global aliases is a one-shot: `flask backfill-association-keywords`.
6. **Duplicate-name character resolution** — in the chapter renderer, `needle_to_character_ids` is a **list** per needle (not a single id). When multiple characters share a needle (two "Lady Cao"s both associated with the same chapter), each one contributes its own MatchExclusion set, and `replace_match` walks candidates in registration order per occurrence — the first one who hasn't excluded that occurrence gets the pill. This lets an admin split ambiguous matches between characters by mirror-excluding: A excludes the occurrences they don't want, B excludes the rest; the renderer resolves each occurrence to whichever character claims it. See `app/blueprints/main/views.py` — the `character_html` dict + `needle_seen` counter + candidate loop.
7. **`build_needle_pattern` rules.** Three things all matter and all were bugs in the naive version, so don't "simplify":
    - **Longest-first sort** of alternatives — Python's `|` is leftmost-first not longest-match, so `"Cao|Cao Cao"` would match `Cao` first in `Cao Cao` and only tag the first three letters.
    - **`\s+` between multi-word tokens** (`Wang Yun` compiles to `Wang\s+Yun`) — a literal space wouldn't match `Wang\nYun` when a name spans a line break.
    - **`(?=\W|$)` trailing context** instead of a hand-rolled punctuation allowlist — colons in dialogue tags (`Wang Yun:`), close-parens, brackets, em-dashes, etc. all match now.
    Callers of the resulting pattern must whitespace-collapse `match.group(0)` before looking it up in dicts keyed by the canonical single-space needle (see `re.sub(r'\s+', ' ', matched)` in `replace_match`).
8. **`Character.book_mention_count` semantics.** Association-aware since commit `cdb3180`: for each character, sums matches only in the chapters they're actually associated with (via `chapter_character`), using that pair's per-chapter `keywords` (or falling back to global labels when empty). Fixed the old bug where two "Lady Cao"s each counted every "Lady Cao" mention across the book. The scalar is cached on the character row and recounted from scratch (no delta math) at: `chapter_associations_add` (single character), `chapter_associations_remove` (single character), `chapter_associations_switch` (both old + new), `edit_character` when labels change, `new_character` on insert, `rescrape-chapter` (every character in the chapter), `rescrape-all-chapters` (every character whose chapter content actually changed), and `flask recount-book-mentions` (bulk). Reads are cheap attribute access on the character row; writes fan out at the trigger points above.
9. **Rescrape safety guarantee.** `flask rescrape-chapter <n>` and `flask rescrape-all-chapters` only touch `chapter.name` and `chapter.content`. They **do not** touch `chapter_character` / `event_chapter` / `chapter_location` M2M rows (or their per-association `keywords` columns) or `match_exclusion` rows. The chapter row keeps the same `id`, so FKs stay intact. Book-mention counts are auto-recounted at the end. The one indirect risk: a MatchExclusion whose fingerprint's `before` window crosses a newly-recovered paragraph's insertion point can silently un-exclude (the fingerprint no longer matches live content) — see the caveat above; those need to be re-×'d via the admin UI.
10. **Polymorphic relationships.** `Url`, `TagAssociation`, and `MatchExclusion` use `(target_type, target_id)` pairs with no FK constraint on `target_id`; each first-class object has a `viewonly` SQLAlchemy relationship filtered to its own table name. Writes happen through the underlying rows directly (admin routes), not through the relationship.
11. **Audit columns.** `created_by` + `last_edited_by` columns sit on every `AbstractObject` row plus `TagAssociation`. ORM `before_insert` / `before_update` hooks (in `app/models/audit.py`) stamp the current Flask-Login user's username (or `'rotk.net_system'` outside a request).
12. **Edit log.** Every admin save also writes an `Edit` row with the model name + row id + a JSON diff of changed fields. Visible at `/admin/edits`.
13. **Hidden prose spans** (`ChapterHiddenSnippet`, `/admin/chapter-edit`). Admin highlights prose → the span is fingerprinted (same `(before, match, after)` shape as MatchExclusion) and REMOVED from the public chapter render entirely (`apply_hidden_snippets(html, rows, admin=False)`); the admin editor renders it as clickable strikethrough instead (`admin=True`). Applied to `chapter.content` BEFORE pill-tagging so hidden text never participates in needle matching, mention counts, or exclusion fingerprints. Distinct concept from MatchExclusion (which keeps text visible, just un-pilled).
14. **Annotations** (`Annotation`, per-paragraph threads). Section identity is content-addressed: `section_text` stores the readable paragraph text; comparisons and hash keys go through `annotation_section_canonical` (strip tags → unescape entities → **remove all whitespace**). All-whitespace-removal is load-bearing: browser `textContent` inserts nothing at tag boundaries while `strip_html_tags` inserts a space, so collapsed-whitespace forms never agree — deleted-whitespace forms do. Icons are server-injected per `<p>` (`inject_annotation_icons`): black = has public (everyone), red + exclamation = has private (admin only), blue hover-revealed = no annotations yet (admin add affordance). Character/location refs are auto-detected at CREATE time from the chapter's associations (`detect_annotation_refs`) and stored on `annotation_character` / `annotation_location` M2Ms — redundant across a thread by accepted design.
15. **Yearly territory maps** (`YearMap`, chapter-page panel). Admin uploads one image per year (184–280) at `/admin/yearly-maps` (Portrait-grade upload hardening: size cap, magic bytes, extension consistency, server-built `<year>.<ext>` filename under `static/yearmaps/`) plus the attribution pair and the year's faction set (chip picker; `year_map_faction` replaced wholesale on every modal save). On the chapter page, `_chapter_years(chapter.date)` parses the free-form date via `parse_date_range` into an inclusive year list ("208" → [208]; integer span edges are exclusive, so last year = ceil(hi) − 1); years that have a YearMap render as tabs in a collapsible header panel — map left in the reusable `image_panzoom.js` viewer, the year's factions as a two-column down-then-across pill list (first auto-selected), and a leader detail pane (faction URLs + per-leader tabs: portrait, roles, faction pills linking to the filtered characters list). No YearMap rows or unparseable/absent `chapter.date` → the panel doesn't render at all.

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
| `flask backfill-annotation-refs [--dry-run]` | Attach auto-detected character/location refs to annotations that predate migration 0016. Skips rows that already have refs (never refreshes). Idempotent. |
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
- **Match exclusion fingerprints** are computed against `strip_html_tags(chapter.content)` (not the raw HTML) and **whitespace-normalised** (`normalize_snippet` collapses newlines/multi-space runs) so a form-round-tripped `\r\n` and a raw `\n` compare equal. Both the admin page and the chapter renderer must use the same trim algorithm — see `_skip_indices_for` in the chapter view, which uses the *combined* pattern (same one `replace_match` uses) filtered to the target needle, so occurrence indices align with `replace_match`'s counter. Wired for `target_type='character'` and `'location'` today; `'event'` is structurally supported (schema is polymorphic) but the UI isn't hooked up yet.
- **Picker datalists** use `value="Name #<id>"` so duplicate-named rows still resolve unambiguously. `admin_picker.js` parses the id out and writes a sibling hidden field. Options can carry a `data-keywords` attribute (comma-delimited name + aliases) which `data-picker-keywords-target="<field_name>"` auto-fills into the keywords field — but only when that field is empty, so admin-typed values are never trampled.
- **`badge_widget` is the universal tag renderer.** Any `AbstractTag`-shaped object (Faction, Role, Tag, UrlType, EventType) renders the same way: three colours + optional Font Awesome icon prefix. Don't hand-roll `<span class="badge">` — use the macro so a new colour-locked column / icon column gets picked up everywhere automatically.

## Known landmines

See `ISSUES.md` for the full running list. Highlights still open:

- Character name fields are typo'd as `courtesty_name` (and `chinese_courtesty_name`) throughout models, forms, and templates. Renaming is a coordinated change (#19).
- Birth/death dates are stored as `String(N)` and can't be range-queried, though widening to fit BC years has shipped (#20).
- **MatchExclusion context-shift after rescrape.** Fingerprints hold ~60 chars around each excluded match. If a rescrape inserts new prose whose text falls within that 60-char window, the stored fingerprint won't match the regenerated one and the exclusion silently stops applying (the row is still there in the DB; it's just orphaned). Re-× via the admin UI re-fingerprints against current content. Affects any chapter whose content changed materially — the `class="2"` scraper fix in `f7a1ab5` recovered 255 blocks across 74 chapters, so historically-excluded snippets near those blocks may need a manual re-flag.
- **Pre-`cdb3180` `book_mention_count` values are stale.** The counter was a global string-match (over-counted duplicates like two "Lady Cao"s). After that commit it's association-aware, but old prod values persist until `flask recount-book-mentions` runs. Any character created / mutated post-commit is fine — the recount fires at all the trigger points. It's the untouched-since-migration rows that carry stale numbers.
- **`Location.geojson = ""` legacy rows.** `new_location` used to `form.populate_obj(location)` without overriding `geojson` with the validator's parsed value, so an empty textarea landed the JSON string `""` in JSONB. Fixed in `11f25f9`, and downstream `has_geo` checks are now truthy (not `is not None`), so newer locations behave. Any pre-fix location with the bad value should get cleaned via `flask clean-empty-location-geojson`.
- **Annotation refs are create-time snapshots — intentionally.** `detect_annotation_refs` runs when the annotation is created. If a character/location association (or its keywords) is added to the chapter AFTER an annotation exists on a paragraph mentioning it, the annotation's refs are NOT retroactively updated. Accepted and preferred for now — annotations may grow richer manual character/location selection later, and auto-resyncing would fight that. `flask backfill-annotation-refs` only fills rows with NO refs at all; it never refreshes existing ones.
- **Annotation section fingerprints share the content-shift caveat.** Like MatchExclusion and ChapterHiddenSnippet, an annotation is keyed to its paragraph's text. If the paragraph's content changes (rescrape recovering a missing block, a hidden-snippet hide/restore inside that paragraph), the canonical form shifts and the annotation orphans — the icon stops appearing, though the row and its thread stay in the DB and remain visible on the admin lists.

## Things to ask before doing

- **Don't run scrapers without confirming.** They hit external sites ~150 times and overwrite/duplicate rows depending on existing state. The current scraper has no upsert logic — re-running will throw IntegrityErrors on the unique constraint and skip rows.
- **Don't enable Flask-Migrate retroactively** without an Alembic baseline plan — `db.create_all()` (now followed by the SQL files in `migrations/`) is the source of truth, and a fresh Alembic autogenerate would not match.
- **The MySQL → Postgres migration** (May 2026) changed: the DB URL builder in `config.py`, the `collation` argument in `app/models/abstract.py` (`utf8mb4_bin` → `C`), the bundled `db` service in `docker-compose.yml` (mysql:8.4 → postgres:16-alpine), `.env.example` (`MYSQL_*` → `POSTGRES_*`), and the requirements (`mysqlclient` / `mysql-connector` → `psycopg[binary]`). The DB was renamed `rotk.net` → `rotk_net` (no dot) to avoid postgres quoting hassles. `docker-compose.prod.yml`, `docker-compose.ambrose.yml`, `db-init/`, and the `nginx/` config were deleted — production now uses `stateful_boilerplate` for TLS/proxy.

## Tests

`tests/` holds a ~600-test pytest suite (see README "Running the tests"
for the run commands). Layout:

- `conftest.py` — the safety guard (refuses any DB not ending `_test`),
  session-scoped schema setup (`db.create_all()` against `rotk_net_test`),
  per-test savepoint-rollback isolation (`db_session`), and `client` /
  `user_client` / `admin_client` fixtures. `admin_client` yields
  `(client, user)` tuples. A `teardown_request` hook pops Flask-Login's
  `g._login_user` cache after every request: test-client requests reuse
  the app context `db_session` holds open, so without the hook the first
  authenticated client's user leaks into every later request in the same
  test (an "anonymous" client would render admin content).
- `factories.py` — `make_*` helpers with unique defaults +
  `associate_character/event/location(chapter, entity, keywords=...)`
  which write the per-association keywords column the way the admin
  endpoints do.
- Pure-function suites (no DB): `test_needle_pattern`,
  `test_annotation_canonical`, `test_hidden_snippets_pure`,
  `test_ref_builders`. DB suites: `test_models`, `test_associations`,
  `test_parser_db`. HTTP suites: `test_auth`, `test_public_routes`,
  `test_association_admin`, `test_chapter_edit_annotations`,
  `test_entity_crud`, `test_year_maps` (admin CRUD + chapter-page
  territory-map panel). Cross-feature: `test_composites` (annotation vs
  hidden-snippet orphaning, Lady Cao mirror-exclusion split, exclusion
  context-shift — several are executable documentation of ACCEPTED
  caveats; if one starts failing after a change, update docs + decide
  intentionally). CLI: `test_cli`.
- When you add a route/feature, add tests in the matching suite; when
  you fix a bug, pin it with a regression test named after the failure
  mode (see the session-bug tests referencing commit hashes in
  docstrings).
- Tests were authored ahead of first execution (no local runner on the
  dev machine) — expect a first-run shakeout pass on ambrose; fix
  fixtures/assertions rather than weakening the tested behaviour.

## Memory

The auto-memory store lives at `~/.claude/projects/-home-renton-Desktop-dev-codedev-webdev-rotk-net/memory/`. Use it for things that should persist across sessions (user preferences, project decisions). Don't store anything in memory that's already derivable from the code or git history.
