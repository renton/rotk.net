# ISSUES.md

A catalogue of things I'd push back on after a first read of the codebase: bugs, design choices I'd reconsider, and tools/practices that would pay for themselves if you adopted them. Not a TODO list — these are starting points for conversation.

Ordered loosely by impact within each section.

## Status

- ✅ = fixed (see git log for the commit)
- ⬜ = open

**Progress:** 22 / 48 resolved.

---

## Security bugs

### 1. ✅ `@admin_required` lets anonymous users through
**File:** `tools/decorators.py:9`

```python
if not current_user.is_administrator:
    abort(403)
```

For authenticated users, `is_administrator` is a `db.Column(Boolean)` — a value. For anonymous users it's defined as a *method* on `AnonymousUser` (`app/models/auth.py:126`). `not <bound method>` is always `False`, so anonymous users **pass** the check. Combined with `@login_required` ahead of it on most routes the door stays shut by accident, but anywhere `@admin_required` is used without `@login_required` (or where one is removed in the future) is wide open.

Fix: make both sides consistent — either both properties or both methods — and call/test them the same way.

### 2. ✅ CSRF disabled in dev
**File:** `config.py:18` — `WTF_CSRF_ENABLED = False` on `DevelopmentConfig`

Dev parity matters most exactly where CSRF bugs hide (form changes). I'd leave CSRF on in dev and just stub a working token in tests.

### 3. ✅ App runs as MySQL `root`
**File:** `config.py:8` — `mysql+mysqldb://root:{MYSQL_ROOT_PASSWORD}@db/rotk.net`

The application user is `root` with full DDL privileges. Create a least-privileged app user (CRUD on the `rotk.net` schema, no GRANT/DROP), and keep root for migrations only.

### 4. ✅ No rate limiting on `/auth/login`
Brute-force protection is absent. `Flask-Limiter` with even a generous limit (e.g. 10/min/IP) is one decorator per route.

### 5. ✅ Two competing Content-Security-Policy headers
**Files:** `app/__init__.py:32-40` (Talisman) and `rotk.py:31-38` (`@app.after_request`)

Talisman emits a permissive CSP that allows `'unsafe-inline'`. The `after_request` hook then overwrites it with a stricter one that drops `'unsafe-inline'`. End result:

- The browser sees the stricter header (the after_request hook clobbers Talisman's value for the same header name).
- That stricter CSP forbids inline event handlers — which is exactly what `build_name_ref_html` emits (`onclick="show_character(...)"` at `tools/book_parser.py:29`).
- So character-tag clicks should be silently dropping in any browser that enforces CSP… unless I'm missing a runtime override.

Pick one CSP source. Move click handling to an event listener attached in a static JS file so the stricter CSP can stand without exceptions.

---

## Correctness bugs

### 6. ✅ `tools/dbm.py` is broken
- `get_col_names` calls `inspect(model)` without importing `inspect` (line 10).
- `update_row` and `delete_all` reference bare `db.session.rollback()` instead of `self.db.session.rollback()` (lines 31, 39).

The module is referenced by `app/__init__.py` (`dbm = DbManager(db)`) but doesn't appear to be called anywhere yet — so this is latent. Either fix it or delete it.

### 7. ✅ `AbstractObject.cleaned_name` and `__repr__` reference `self.display_name`
**File:** `app/models/abstract.py:24, 32, 48`

`display_name` is never defined on `AbstractObject` or any descendant. Every call to `cleaned_name` or `repr()` on a Character/Chapter/etc. will raise `AttributeError`. The `__repr__` on `Character`/`Chapter`/`Faction`/`Role` correctly uses `self.name`, which is what masks the bug — but the abstract `__repr__` and `cleaned_name` are dead/broken.

### 8. ✅ `User.generate_*_token` is calling the wrong `itsdangerous` API
**File:** `app/models/auth.py`

```python
s = Serializer(current_app.config['SECRET_KEY'], expiration)   # wrong signature
return s.dumps({'confirm': self.id}).decode('utf-8')           # dumps returns str in 2.x
```

In `itsdangerous` 2.x, `URLSafeTimedSerializer` takes `(secret_key, salt=...)`, not `(secret_key, expiration)`. Expiration goes to `loads(..., max_age=...)`. And `.decode('utf-8')` on a `str` will `AttributeError`. Confirmation, password reset, and email change are all currently dead code; none of these flows have routes wired up yet, so the bugs haven't surfaced.

### 9. ✅ `latest_faction` relationship has an ambiguous join
**File:** `app/models/character.py:43-44`

`Character` has both `factions` (many-to-many via `character_factions_association`) AND `latest_faction_id` as a direct FK to the same `faction` table. SQLAlchemy is given a `foreign_keys=[latest_faction_id]` hint which makes this work, but it's a smell — the "current" faction should either:

- be derivable from the `factions` collection (with an `is_current` flag on the association row), or
- entirely replace the M2M (if "past factions" is just historical noise).

Modelling it as both columns *and* a relationship invites drift (you can have `latest_faction` set to a faction that's not in `factions`).

### 10. ✅ Chapter ↔ Character association table is never populated
**File:** `app/models/character.py:47-56`

`chapter_character` is defined as a many-to-many, but `get_characters_for_chapter` (`tools/book_parser.py:6`) loads every character and regex-scans the chapter text on each render. Two consequences:

1. Each `/chapter/<n>` request does O(N_characters × len(chapter_text)) work.
2. The "search by chapter" use case isn't queryable from the DB.

This should be computed once during scrape (or in a backfill command) and stored.

### 11. ✅ `chapter.content` is mutated on the SQLAlchemy session at render time
**File:** `app/blueprints/main/views.py:49`

```python
chapter.content = modified_text
```

`chapter` is still session-attached. The `with db.session.no_autoflush:` block prevents autoflush but doesn't stop a later commit from persisting the mutated content (the page contains `<span class="character-ref" ...>` HTML now). If anything in the same request lifecycle commits, the DB row is corrupted.

Render into a local variable; pass that to the template; never assign back to `chapter.content`.

### 12. ✅ Pre-emptive index page does not order chapters
**File:** `app/blueprints/main/views.py:14` — `Chapter.query.all()` returns rows in insertion order, which today happens to match `chapter_num` but is not guaranteed. Add `.order_by(Chapter.chapter_num)`.

### 13. ✅ `edit_faction`/`edit_role` redirect to a listing endpoint with an unused `id` kwarg
**File:** `app/blueprints/main/views.py:149, 178`

```python
return redirect(url_for("main.factions", id=faction.id))
```

`main.factions` doesn't take an `id`. The kwarg becomes `?id=…` in the URL which is harmless but confusing — likely a copy/paste from a planned per-faction detail view.

### 14. ✅ Scraper `latest_faction` logic is fragile
**File:** `tools/scraper.py:228-243`

Latest faction is hardcoded as `row_factions[0]` of the 6th `<td>` of the Wikipedia row. The Wikipedia format is human-edited and any reorder/split of columns silently corrupts the data. Also: column 6 *and* column 7 both contribute to the `factions` set, but only 6 is treated as "current" — there is no comment explaining what column 7 is supposed to represent.

### 15. ✅ `RegistrationForm` and reset flows have forms but no routes
**Files:** `app/blueprints/auth/forms.py`, `app/templates/auth/register.html`, etc.

Templates exist, forms exist, but only `login`/`logout` views are registered. Either finish wiring them (with the `itsdangerous` API fixed — see #8) or delete the orphaned forms/templates.

### 16. ✅ `register.html` uses the wrong Jinja import path
**File:** `app/templates/auth/register.html:2`

```jinja
{% import "bootstrap/wtf.html" as wtf %}
```

That path is Flask-Bootstrap (3.x). The app uses Bootstrap-Flask, which exposes `bootstrap5/form.html`. The template would 500 the moment a register route was added.

### 17. ✅ `Portrait.__repr__` says "Link"
**File:** `app/models/character.py:104` — copy-paste typo. Doesn't break anything; will confuse logs.

### 18. ✅ `datetime.utcnow` is deprecated
**File:** `app/models/auth.py:16-17, 94` — use `datetime.now(datetime.UTC)` going forward.

---

## Naming / data-model nits

### 19. ⬜ "courtesty" should be "courtesy"
Appears in `Character.courtesty_name`, `Character.chinese_courtesty_name`, `EditCharacterForm.courtesty_name` / `chinese_courtesty_name`. The English label `"Courtesty Name"` is also visible in the admin UI. This is a coordinated rename (model + form + template + DB migration) — worth doing once before more data piles up.

### 20. ⬜ Birth/death dates as `String(4)`
**File:** `app/models/character.py:12-13`

- Can't be sorted, ranged, or compared as dates.
- Can't represent BC dates (which historical 3K characters legitimately have).
- Can't represent "unknown" distinct from empty.

A nullable `Integer` (year, signed for BC) is much closer to right. Or `String` if you want to keep "circa 200" / "?–220" prose intact — but then own the "no comparisons" tradeoff explicitly.

### 21. ⬜ `aliases` as a comma-delimited string
**File:** `app/models/abstract.py:14`

Querying "who's an alias of X" is not possible. The book-parser splits this string at runtime on every chapter render. A proper `aliases` relationship (one-to-many) would let the parser build its lookup table once and would make the data queryable.

### 22. ⬜ `Role` names are forced lowercase, `Faction` names are not
**File:** `tools/scraper.py:223-236` — roles get `.lower()`, factions don't. There's no documented reason. Pick one normalisation rule and apply it consistently (or document why they differ — e.g. "factions are proper nouns").

### 23. ⬜ Unique constraint on `(name, birth_date, death_date, ancestral_home)`
**File:** `app/models/character.py:62-64`

Many minor characters have empty birth/death/ancestral fields. Two unrelated characters with the same name and blanks across the others will collide. Either:

- include `courtesty_name` and `chinese_name` in the constraint, or
- accept that there can be duplicates and disambiguate by surrogate key + manual editing.

### 24. ⬜ `Faction.name` / `Role.name` collation is `utf8mb4_bin`
**File:** `app/models/abstract.py:37`

This makes tag lookups case-sensitive. The scraper sometimes lowercases (roles) and sometimes doesn't (factions); a future maintainer pasting `Wei` vs `wei` into the form will silently create a duplicate. If case sensitivity is actually wanted, document it; otherwise switch to a `_ci` collation.

---

## Infrastructure / DX

### 25. ⬜ No tests
No `tests/` directory. `rotk.py` has commented-out scaffolding for `unittest` + `coverage`. The whole inline-tagging regex pipeline is exactly the kind of code that benefits from a unit test (name-with-apostrophe, name-at-end-of-paragraph, name-inside-HTML-tag). Pytest + a couple of fixtures is two hours of work.

### 26. ⬜ No Alembic / Flask-Migrate
Schema changes today are "drop tables, change models, `flask create-all`, re-scrape". With ~150 HTTP fetches per scrape that's slow, brittle, and lossy (you lose any admin edits). Wire up Flask-Migrate with a baseline migration of the current schema.

### 27. ✅ `Talisman(force_https=True)` unconditionally
**File:** `app/__init__.py:40`

Forces HSTS even in dev. After the first browser visit to `http://localhost`, the browser caches HSTS and forces HTTPS for `localhost`, which the dev server doesn't speak. Drive this from config: `force_https` in `ProductionConfig` only.

*(Resolved by dropping Talisman entirely once the `stateful_boilerplate` Caddy started handling HSTS / HTTPS redirect / security headers at the edge.)*

### 28. ⬜ `SQLALCHEMY_ECHO = True` in base config
**File:** `config.py:10`

Every SQL statement is logged in *prod* as well as dev. Move to `DevelopmentConfig`, or gate behind `DEBUG`.

### 29. ✅ `config["default"]` referenced but not defined
**File:** `rotk.py:27` — `create_app(os.getenv('FLASK_ENV') or 'default')`. The `config` dict in `config.py:33-36` has only `'development'` and `'production'` keys. If `FLASK_ENV` is unset, this is a `KeyError`. Add `'default': DevelopmentConfig`.

*(Fixed incidentally while sorting out the MySQL non-root user — see commit `6835672`.)*

### 30. ⬜ Two MySQL drivers pinned
**File:** `requirements.txt:22-23`

`mysql-connector==2.2.9` (Oracle, last touched 2017) and `mysqlclient==2.2.6` (the C-based one) are both installed. The connection URI uses `mysql+mysqldb://` which is `mysqlclient`. Drop `mysql-connector`.

### 31. ⬜ `dominate` and `visitor` in requirements look unused
Grep doesn't show them being imported. They're transitive remnants from Flask-Bootstrap (3.x). Confirm and remove.

### 32. ✅ `boot.sh` runs `flask deploy` on every start, but `deploy` is a `pass`
**Files:** `boot.sh:4`, `rotk.py:144-148`

Either implement `deploy` (run migrations, seed admin user, etc.) or remove the loop. Currently every container restart does ~one extra round-trip through `pass`.

*(Resolved: dropped the retry loop from boot.sh. The `flask deploy` command itself stays as a no-op stub for when migrations land.)*

### 33. ✅ `--reload` in gunicorn production command
**File:** `boot.sh:23`

`--reload` is for dev. In prod it makes gunicorn watch files and restart workers — wasted CPU and a potential foot-gun on a production volume mount. Drop it from the prod path.

### 34. ⬜ `volumes: - .:/rotk.net` in the *production* compose
**File:** `docker-compose.prod.yml:19`

Bind-mounting the source tree into prod means the running container reflects whatever's on disk on the host. Combined with `--reload`, you have a "live" production that updates on `git pull` without a deploy step. Could be intentional, but it's load-bearing magic that's not documented anywhere.

### 35. ⬜ `db-data/` checked into the repo
**File:** layout (visible in `ls -la`)

It's in `.gitignore` but the directory exists on disk; that's fine. Make sure no stale MySQL files have been committed in history — `git log -- db-data/` will tell you.

### 36. ⬜ `.env` is in the repo according to `ls` (committed?)
The file shows in `ls -la`. `.gitignore` excludes it. Run `git ls-files .env` once to verify it's not actually tracked.

### 37. ⬜ No logging setup
`ProductionConfig.init_app` adds a `StreamHandler` at INFO but the app doesn't `app.logger.info(...)` anywhere meaningful. With gunicorn `--access-logfile -` you get request logs but nothing structured (request IDs, timing, errors). A 30-line `structlog`/`python-json-logger` setup pays for itself the first time you have to diagnose a prod issue.

### 38. ⬜ No CI
A `.github/workflows/ci.yml` that runs `pytest` + `ruff` + `mypy` on every PR is a couple of hours to set up and would have caught at least #6, #8, #16, and #29 above.

---

## Things I'd consider adding

### 39. ⬜ A Map / Locations model
`app/models/location.py` is a placeholder. There's a "Map" link in the navbar that goes nowhere, and a "Map" accordion item in the chapter sidebar that shows lorem-ipsum. If maps are on the roadmap, a `Location` model + a JS map (Leaflet over a stylized China map) would be a striking feature.

### 40. ⬜ Event / Battle model
`app/models/event.py` is also a placeholder. Modelling battles (with date, location, participants, outcome) would let you build a "battles in this chapter" sidebar or a timeline view across all 120 chapters. The novel is *built* on battles — they're a much bigger draw than character bios alone.

### 41. ⬜ Front-end tooling
Not a SPA, not even close — but you do have inline JS (`show_character`) sitting in a Jinja template, and you'll grow more. Consider:

- A tiny `static/js/` directory served from Flask, no bundler.
- Or, if you want components, **htmx** + **Alpine.js** (server-rendered, no build step, small total payload). Fits the "Flask-rendered HTML" shape of the app perfectly.

Skip React/Next.js — there's nothing here that justifies the complexity.

*(Partially addressed in #5: there's now a `static/js/` directory and `chapter.js`. The "consider htmx/Alpine" recommendation still stands.)*

### 42. ⬜ Caching
`@cache` on the chapter view (chapter content rarely changes) would make a noticeable difference because `get_characters_for_chapter` is O(characters × text) per request. Flask-Caching with a Redis backend, or even `functools.lru_cache` keyed by chapter_id for the rendered HTML, would help.

*(Partially mitigated by #10's chapter_character cache: chapter view no longer scans every character on every render. End-to-end caching of the rendered HTML would still help.)*

### 43. ⬜ Search across the prose
A full-text index on `chapter.content` (MySQL `FULLTEXT`, or pull in MeiliSearch / Typesense if you want speed) opens up "find every chapter mentioning Lü Bu" as a feature.

### 44. ⬜ Character portraits as a real feature
The `Portrait` model exists but no upload/admin flow. Currently every character renders the same `static/test.webp` placeholder. Either implement (S3 / local file upload + admin) or delete the model.

### 45. ⬜ Markdown for character notes
The `notes` field on every `AbstractObject` is `db.Text` rendered as plain text. Adding `markdown` parsing (sanitised) would let admins write proper bios.

### 46. ⬜ Type hints + `ruff` + `mypy`
The codebase is small enough that full type coverage is achievable. Adds maintainability and pairs nicely with the IDE / CI suggestions above.

### 47. ⬜ SQLAlchemy 2.0-style query API
Models use `Model.query.all()` (legacy 1.x-style). The 2.0 idiom is `db.session.scalars(select(Model)).all()`. Mixing the two styles is fine but consistency would be a small win.

### 48. ⬜ Docs for the bootstrap dance
There's no single command that takes a fresh checkout to "site has content". The README I just wrote sketches it, but a `make bootstrap` target (or a `flask init`-like command that runs `create-all → scrape-book → scrape-characters → build-chapter-character-association`) would make onboarding a one-liner.
