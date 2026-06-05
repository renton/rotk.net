import os, sys

# Load .env if present, but never override values that are already in the
# environment. In docker-compose deployments the compose `environment:`
# block is the source of truth; a baked-in .env (or a stale .env in a
# bind-mount) must not silently replace what compose set.
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=False)

import click
from sqlalchemy.exc import IntegrityError
from app import create_app, db
from tools.scraper import scrape_rotk_book, scrape_rotk_characters
from tools.book_parser import get_characters_for_chapter, scan_chapter_for_characters, scan_chapter_for_locations
from flask import render_template, request, jsonify
import os, time, urllib.parse

# COV = None
# if os.environ.get('FLASK_COVERAGE'):
#     import coverage
#     COV = coverage.coverage(branch=True, include='app/*')
#     COV.start()

# from flask_migrate import Migrate, upgrade
from app.models import \
    Chapter, Character, Faction, Role, User, Tag, TagAssociation, Location, LocationType
from app.models.character import Portrait, PORTRAIT_DIR

app = create_app(os.getenv('FLASK_ENV') or 'default')

# migrate = Migrate(app, db)

@app.cli.command()
def build_chapter_character_association():
    """Populate the chapter_character table by regex-scanning every chapter
    for every character's names/aliases. Idempotent — clears existing rows
    for each chapter before refilling so reruns reflect current data."""
    chapters = Chapter.query.order_by(Chapter.chapter_num).all()
    total = 0
    for chapter in chapters:
        chapter.characters = scan_chapter_for_characters(chapter)
        total += len(chapter.characters)
        print(f"chapter {chapter.chapter_num}: {len(chapter.characters)} characters")
        db.session.commit()
    print(f"\nDone. {total} character/chapter rows.")


@app.cli.command()
def build_location_chapter_association():
    """Populate the chapter_location table by regex-scanning every chapter
    for every location's name + aliases. Mirrors
    build-chapter-character-association — idempotent (the M2M assignment
    is a full replacement per chapter, so re-running picks up any new
    locations / new aliases without manual cleanup) and skips
    soft-deleted Locations so merge sources don't leak back in.

    Per-chapter `keywords` overrides on the chapter_location M2M are
    NOT touched here — this CLI sets membership only. Use the
    /admin/location-associations page to refine specific chapter
    matches after the bulk scan."""
    chapters = Chapter.query.order_by(Chapter.chapter_num).all()
    total = 0
    for chapter in chapters:
        chapter.locations = scan_chapter_for_locations(chapter)
        total += len(chapter.locations)
        print(f"chapter {chapter.chapter_num}: {len(chapter.locations)} locations")
        db.session.commit()
    print(f"\nDone. {total} location/chapter rows.")


@app.cli.command()
def scrape_book():
    chapters = scrape_rotk_book()

    for i, content in enumerate(chapters):
        title = content[0]
        copy = content[1]
        try:
            chapter = Chapter(
                name=title,
                chapter_num=i+1,
                content=copy,
            )        
            db.session.add(chapter)
            db.session.commit()
        except Exception as e:
            print(e)
            db.session.rollback()

@app.cli.command()
def scrape_characters():
    characters, factions, roles = scrape_rotk_characters()

    # add factions
    for i, faction in enumerate(factions):
        try:
            new_faction = Faction(
                name=faction
            )
            db.session.add(new_faction)    
            db.session.commit()
        except Exception as e:
            print(f"Duplicate key error for faction {faction}")
            db.session.rollback()

    # add roles
    for role in roles:
        try:
            new_role = Role(
                name=role
            )
            db.session.add(new_role)
            db.session.commit()

        except IntegrityError as e:
            print(f"Duplicate key error for role {role}")
            db.session.rollback()

    # get faction index
    faction_index = {faction.name: faction for faction in Faction.query.all()}

    # get role index
    role_index = {role.name: role for role in Role.query.all()}

    bad_eggs = []
    # add characters
    for character in characters:
        try:
            primary_faction_name = character.pop('primary_faction', None)
            primary_faction_obj = faction_index.get(primary_faction_name) if primary_faction_name else None

            faction_objs = [faction_index[f] for f in character['factions'] if f in faction_index]
            role_objs = [role_index[r] for r in character['roles'] if r in role_index]

            character['factions'] = faction_objs
            character['roles'] = role_objs

            new_character = Character(**character)
            new_character.set_primary_faction(primary_faction_obj)
            db.session.add(new_character)

            db.session.commit()
        except Exception as e:
            print(e)
            bad_eggs.append((e, character))
            db.session.rollback()

    print("\n==========")
    for egg in bad_eggs:
        print(egg)

@app.cli.command()
@click.option('--character-id', type=int, default=None,
              help='Scrape just this character (by id). Omit to scrape all.')
@click.option('--skip-existing/--refresh', default=True,
              help='Skip characters that already have a Koei portrait. '
                   '--refresh re-fetches and adds any new images that aren\'t already stored.')
@click.option('--limit', type=int, default=None,
              help='Stop after N successful downloads in total (across all characters).')
@click.option('--max-per-character', type=int, default=200,
              help='Cap downloads per character (Cao Cao alone has 100+ images on Koei).')
@click.option('--delay', type=float, default=0.5,
              help='Seconds between requests.')
def scrape_koei_images(character_id, skip_existing, limit, max_per_character, delay):
    """Scrape ALL Koei portraits for each character.

    Lists every image on the character's wiki page via the MediaWiki API,
    keeps only filenames that start with the character's name, downloads
    each one, and tags the resulting Portrait with the game variant code
    parsed from the filename (e.g. 'DW9' from 'Cao Cao (DW9).png'). Tags
    are created on demand with a name-seeded random palette."""
    from tools.image_scrapers import koei_fandom

    if character_id is not None:
        characters = [Character.query.get_or_404(character_id)]
    else:
        characters = Character.query.order_by(Character.name).all()

    portraits_dir = os.path.join(app.static_folder, PORTRAIT_DIR)
    os.makedirs(portraits_dir, exist_ok=True)

    successes = 0
    misses = 0
    skipped_chars = 0
    errors = 0
    hit_limit = False

    for character in characters:
        if hit_limit:
            break

        if skip_existing:
            has_any = Portrait.query.filter_by(
                character_id=character.id,
                source_site=koei_fandom.SITE_NAME,
            ).first() is not None
            if has_any:
                skipped_chars += 1
                continue

        print(f"[{character.id}] {character.name}: looking up images...", flush=True)
        try:
            scraped_list = koei_fandom.scrape(
                character,
                max_images=max_per_character,
            )
        except Exception as exc:
            print(f"  ERROR ({exc})")
            errors += 1
            continue

        if not scraped_list:
            print("  no images found")
            misses += 1
            time.sleep(delay)
            continue

        # Dedupe against the URLs we've already stored for this character so
        # --refresh runs only download genuinely-new images.
        already_have = {
            row[0] for row in db.session.query(Portrait.image_url)
            .filter_by(character_id=character.id)
            .all()
        }

        new_count = 0
        dup_count = 0
        err_count = 0
        for scraped in scraped_list:
            if scraped.image_url in already_have:
                dup_count += 1
                continue

            try:
                filename = _download_image(
                    scraped.image_url,
                    portraits_dir,
                    character.id,
                    'koei',
                )
            except Exception as exc:
                print(f"  fail: {scraped.variant_tag or 'image'} — {exc}")
                err_count += 1
                continue

            portrait = Portrait(
                name=character.name,
                character_id=character.id,
                image_url=scraped.image_url,
                filename=filename,
                description=scraped.description,
                source_url=scraped.source_url,
                source_site=scraped.source_site,
            )

            tag = None
            if scraped.variant_tag:
                tag, _ = Tag.get_or_create(scraped.variant_tag)

            db.session.add(portrait)
            db.session.flush()   # populates portrait.id (and tag.id if newly added)

            if tag is not None:
                db.session.add(TagAssociation(
                    tag_id=tag.id,
                    target_type='portrait',
                    target_id=portrait.id,
                ))

            db.session.commit()
            already_have.add(scraped.image_url)
            successes += 1
            new_count += 1
            size = os.path.getsize(os.path.join(portraits_dir, filename))
            tag_str = f" tag={scraped.variant_tag}" if scraped.variant_tag else ""
            print(f"  ok  {filename}  ({size:,} B){tag_str}")

            if limit is not None and successes >= limit:
                print(f"\nhit --limit {limit}; stopping.")
                hit_limit = True
                break

            time.sleep(delay)

        print(f"  -> {new_count} new, {dup_count} dup, {err_count} err")

    print(f"\nDone. ok={successes} miss={misses} skipped_chars={skipped_chars} err={errors}")


_VALID_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
# Polite identifying UA without "scraper" in it. Some CDNs (Fandom's
# static.wikia.nocookie.net included) serve interstitials to bot-flavoured
# UAs even when they let the bytes through with status 200.
_DOWNLOAD_UA = (
    "rotk.net/1.0 (+https://rotk.net; "
    "an annotated Romance of the Three Kingdoms edition)"
)


def _extension_for(image_url, content_type):
    """Pick a file extension from Content-Type first, falling back to the URL
    path with Fandom's `/revision/<rev>` suffix stripped. Returns one of the
    members of _VALID_EXTS or '.jpg' as a last resort."""
    import mimetypes

    if content_type:
        ext = mimetypes.guess_extension(content_type.split(';')[0].strip())
        if ext in _VALID_EXTS:
            return ext
        if ext == '.jpe':   # mimetypes quirk for image/jpeg
            return '.jpg'

    path = urllib.parse.urlparse(image_url).path
    # Fandom CDN: ".../foo.png/revision/latest" — strip the revision suffix
    # so splitext sees the real basename.
    if '/revision/' in path:
        path = path.split('/revision/')[0]
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in _VALID_EXTS else '.jpg'


def _download_image(image_url, save_dir, character_id, source_tag):
    """Stream `image_url` to disk under `save_dir`. Returns the basename
    (e.g. '42_koei.png') for storage in Portrait.filename. Raises with a
    descriptive message if the response doesn't look like a real image."""
    import requests as _requests

    response = _requests.get(
        image_url,
        headers={"User-Agent": _DOWNLOAD_UA},
        timeout=30,
        stream=True,
    )
    response.raise_for_status()

    content_type = response.headers.get('Content-Type', '')
    if not content_type.lower().startswith('image/'):
        raise ValueError(
            f"expected image/*, got Content-Type {content_type!r} "
            f"(likely an anti-bot interstitial or redirect)"
        )

    ext = _extension_for(image_url, content_type)

    # Counter suffix lets multiple portraits per character/site coexist
    # without clobbering each other on re-runs (--refresh).
    n = 0
    while True:
        suffix = f"_{n}" if n else ""
        filename = f"{character_id}_{source_tag}{suffix}{ext}"
        path = os.path.join(save_dir, filename)
        if not os.path.exists(path):
            break
        n += 1

    total = 0
    with open(path, 'wb') as f:
        for chunk in response.iter_content(8192):
            if chunk:
                f.write(chunk)
                total += len(chunk)

    # A real portrait is at minimum a few KB. If we got essentially nothing,
    # don't leave a broken file lying around.
    if total < 512:
        try:
            os.remove(path)
        except OSError:
            pass
        raise ValueError(f"downloaded file too small ({total} bytes) — discarded")

    return filename


@app.cli.command()
@click.option('--faction-id', type=int, default=None,
              help='Randomize just one faction (by id). Omit to do all factions.')
@click.option('--seed', type=int, default=None,
              help='Optional RNG seed for reproducible palettes.')
@click.option('--dry-run', is_flag=True, default=False,
              help='Print the new palette without writing to the DB.')
def randomize_faction_colours(faction_id, seed, dry_run):
    """Assign each faction a new random bg/font/border palette.

    Background is sampled in HSL with saturated mid-lightness; font is
    forced to black or white based on WCAG relative luminance so the
    badge stays readable; border is a same-hue shift of the bg."""
    _randomize_tag_colours(Faction, "faction", faction_id, seed, dry_run)


@app.cli.command()
@click.option('--role-id', type=int, default=None,
              help='Randomize just one role (by id). Omit to do all roles.')
@click.option('--seed', type=int, default=None,
              help='Optional RNG seed for reproducible palettes.')
@click.option('--dry-run', is_flag=True, default=False,
              help='Print the new palette without writing to the DB.')
def randomize_role_colours(role_id, seed, dry_run):
    """Assign each role a new random bg/font/border palette. Same colour-
    selection logic as randomize-faction-colours; see that command's docs."""
    _randomize_tag_colours(Role, "role", role_id, seed, dry_run)


def _randomize_tag_colours(model, label, target_id, seed, dry_run):
    """Shared driver for the two randomize-*-colours commands. `model` is
    Faction or Role (both inherit AbstractTag, which has the colour cols)."""
    import random as _random
    from tools.colours import randomize_palette

    rng = _random.Random(seed) if seed is not None else _random.Random()

    if target_id is not None:
        tags = [model.query.get_or_404(target_id)]
    else:
        tags = model.query.order_by(model.name).all()

    if not tags:
        print(f"No {label}s to update.")
        return

    for tag in tags:
        bg, font, border = randomize_palette(rng=rng)
        print(f"[{tag.id}] {tag.name:30s} bg={bg} font={font} border={border}")
        if not dry_run:
            tag.bg_colour = bg
            tag.font_colour = font
            tag.border_colour = border
            db.session.add(tag)

    if dry_run:
        print(f"\nDry run — no changes committed ({len(tags)} {label}s).")
    else:
        db.session.commit()
        print(f"\nUpdated {len(tags)} {label}(s).")


@app.cli.command()
@click.option('--preferred-tag', default='1MROTK',
              help='Tag name to prefer when picking. Exact name match. '
                   'If no portrait of the character has this tag, falls '
                   'back to a random pick from any of their portraits.')
@click.option('--seed', type=int, default=None,
              help='Optional RNG seed for reproducible picks.')
@click.option('--dry-run', is_flag=True, default=False,
              help='Print what would be done without writing to the DB.')
def assign_default_portraits(preferred_tag, seed, dry_run):
    """For each character with images but none currently visible, promote
    one to be the character's default (which also makes it visible).

    Pick policy:
      1. Prefer a portrait tagged with --preferred-tag, chosen at random
         from the matches.
      2. If no portrait has that tag, pick any active portrait at random.

    Characters with no portraits are skipped. Characters that already have
    at least one visible portrait are skipped (we don't disturb existing
    defaults). Sorting portraits by id before the random pick makes runs
    with the same --seed deterministic."""
    import random as _random
    from sqlalchemy.orm import selectinload

    rng = _random.Random(seed) if seed is not None else _random.Random()
    preferred_tag = (preferred_tag or '').strip()

    # Eager-load portraits + tags so the per-character loop doesn't N+1.
    characters = (
        Character.query
        .options(selectinload(Character.portraits).selectinload(Portrait.tags))
        .filter(Character.is_deleted.is_(False))
        .order_by(Character.id)
        .all()
    )

    updated = 0
    no_portraits = 0
    already_visible = 0
    preferred_picks = 0
    fallback_picks = 0

    for character in characters:
        active = sorted(
            (p for p in character.portraits if not p.is_deleted),
            key=lambda p: p.id,
        )
        if not active:
            no_portraits += 1
            continue
        if any(not p.is_hidden for p in active):
            already_visible += 1
            continue

        preferred = [
            p for p in active
            if any(t.name == preferred_tag for t in p.tags)
        ]
        if preferred:
            chosen = rng.choice(preferred)
            source_label = f"preferred ({preferred_tag})"
            preferred_picks += 1
        else:
            chosen = rng.choice(active)
            source_label = "random fallback"
            fallback_picks += 1

        print(
            f"[{character.id}] {character.name}: -> {chosen.filename} "
            f"[{source_label}]"
        )

        if not dry_run:
            # Clear default on any other portraits for this character so
            # the partial unique index doesn't reject the insert.
            Portrait.query.filter(
                Portrait.character_id == character.id,
                Portrait.id != chosen.id,
            ).update({'is_default': False})
            chosen.is_default = True
            chosen.is_hidden = False    # defaults are always visible
            updated += 1

    if dry_run:
        print(
            f"\nDry run. Would update {preferred_picks + fallback_picks} "
            f"character(s)."
        )
    else:
        db.session.commit()
        print(f"\nDone. Updated {updated} character(s).")

    print(
        f"Summary: {preferred_picks} preferred, {fallback_picks} fallback, "
        f"{already_visible} already had a visible portrait, "
        f"{no_portraits} had no portraits."
    )


@app.cli.command()
def recount_book_mentions():
    """Recompute Character.book_mention_count for every character.

    Run after scraping new chapters or after editing character aliases.
    Re-stripping HTML and re-scanning all chapters takes a couple of
    minutes for the full book × 1500 characters; this is why we cache
    the result on Character rather than computing it on every page load."""
    from tools.book_parser import count_mentions_per_character

    chapters = Chapter.query.all()
    characters = Character.query.all()
    print(f"Scanning {len(chapters)} chapters for {len(characters)} characters...")

    counts = count_mentions_per_character(chapters, characters)
    updated = 0
    for character in characters:
        new_count = counts.get(character.id, 0)
        if character.book_mention_count != new_count:
            character.book_mention_count = new_count
            updated += 1
    db.session.commit()

    print(f"Updated {updated} characters.")


@app.cli.command()
def create_all():
    db.create_all()


_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), 'migrations')


@app.cli.command()
def apply_migrations():
    """Apply unapplied SQL migrations from the migrations/ directory.

    Each .sql file in migrations/ is run in lexicographic filename order;
    files already recorded in the _schema_migrations table are skipped.
    Each file runs in its own transaction so a failure aborts that file
    cleanly and the runner stops. Files are tracked by exact filename, so
    don't rename existing migration files after they've been applied
    anywhere — pick a new number and add a new file instead.

    Idempotent on already-applied files (skipped). Each file should itself
    be idempotent (use IF NOT EXISTS / IF EXISTS) so re-applying a partial
    failure picks up cleanly.
    """
    from sqlalchemy import text

    if not os.path.isdir(_MIGRATIONS_DIR):
        print(f"No migrations directory at {_MIGRATIONS_DIR}.")
        return

    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            filename   TEXT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT now()
        )
    """))
    db.session.commit()

    applied = {
        row[0] for row in db.session.execute(
            text("SELECT filename FROM _schema_migrations")
        )
    }

    files = sorted(
        f for f in os.listdir(_MIGRATIONS_DIR)
        if f.endswith('.sql') and not f.startswith('.')
    )
    if not files:
        print("No .sql migration files found.")
        return

    new_count = 0
    for filename in files:
        if filename in applied:
            print(f"  skip {filename}")
            continue
        path = os.path.join(_MIGRATIONS_DIR, filename)
        with open(path) as f:
            sql = f.read()
        print(f"  apply {filename} ...", flush=True)
        try:
            db.session.execute(text(sql))
            db.session.execute(
                text("INSERT INTO _schema_migrations (filename) VALUES (:f)"),
                {'f': filename},
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            print(f"  FAIL {filename}: {exc}")
            print("  stopping; fix the file and re-run.")
            return
        new_count += 1
        print(f"  ok   {filename}")

    print(f"\nDone. {new_count} new migration(s) applied; {len(applied)} were already in place.")


# Canonical seed list for `flask seed-location-types`. Edit here when
# you want to add a new standard type; re-running the command picks up
# additions and skips anything already in the DB.
#
# The first four (Province → Commandery → County → City) form the
# conventional admin-division chain wired into
# LOCATION_TYPE_PARENT_HIERARCHY in app/models/location.py. The rest are
# free-form types the book uses constantly — they can parent to any
# ancestor type. Admins can also create more from the LocationType admin
# page; this CLI only owns the *initial* set.
_STANDARD_LOCATION_TYPES = [
    'Province',
    'Commandery',
    'County',
    'City',
    'Settlement',
    'Pass',
    'Landmark',
    'Building',
    'Mountain',
    'River',
    'Battlefield',
]


@app.cli.command()
def seed_location_types():
    """Insert the standard set of LocationTypes (Province, Commandery,
    County, City, Settlement, Pass, Landmark, Building, Mountain, River,
    Battlefield) if they don't already exist. Idempotent — re-run any
    time to pick up additions to the standard list without touching
    admin-created types."""
    added = 0
    for name in _STANDARD_LOCATION_TYPES:
        if LocationType.query.filter_by(name=name).first():
            print(f"  exists: {name}")
            continue
        db.session.add(LocationType(name=name))
        added += 1
        print(f"  added:  {name}")
    if added:
        db.session.commit()
    print(f"\n{added} location type(s) added; {len(_STANDARD_LOCATION_TYPES) - added} already in place.")


# ----- import-admin-divisions ---------------------------------------------

import csv as _csv
import re as _re

# Default CSV path is resolved against the project root (where rotk.py
# lives) so the command works regardless of the shell's cwd.
_DEFAULT_DIVISIONS_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'data', '3k_admin_divisions.csv',
)

# Continuous CJK block — captured group is the Chinese-name portion of a
# cell. Used to peel "Bing 并州" → ("Bing", "并州"), "Qiaomen 橋門 (town)"
# → ("Qiaomen (town)", "橋門"), etc.
_CJK_BLOCK_RE = _re.compile(r'[一-鿿]+(?:[一-鿿\s]*[一-鿿])?')

# Parenthetical type marker in column 4 cells (e.g. "(town)", "(city)").
# Mapped to one of the LocationType names that `seed-location-types`
# inserts. Anything outside this map leaves location_type NULL on
# insert — admin can backfill from the UI.
_COL4_PAREN_RE = _re.compile(r'\(\s*([A-Za-z]+)\s*\)')
_COL4_TYPE_MAP = {
    'town':       'Settlement',
    'village':    'Settlement',
    'settlement': 'Settlement',
    'city':       'City',
    'pass':       'Pass',
    'gate':       'Building',
}


def _split_en_zh(cell):
    """Split a CSV cell into (english, chinese). Chinese is the
    contiguous CJK block (with any whitespace it contains); English is
    everything else, whitespace-normalised. Empty cells return ('', '')."""
    if not cell:
        return '', ''
    m = _CJK_BLOCK_RE.search(cell)
    if not m:
        return ' '.join(cell.split()), ''
    english = ' '.join((cell[:m.start()] + cell[m.end():]).split())
    chinese = m.group(0).strip()
    return english, chinese


def _detect_col4_type_name(cell):
    """Return the LocationType.name implied by a "(type)" marker in a
    column-4 cell, or None if no recognised marker is present."""
    m = _COL4_PAREN_RE.search(cell)
    if not m:
        return None
    return _COL4_TYPE_MAP.get(m.group(1).strip().lower())


@app.cli.command()
@click.argument('path', type=click.Path(dir_okay=False),
                default=_DEFAULT_DIVISIONS_CSV, required=False)
@click.option('--dry-run', is_flag=True,
              help='Parse the CSV and show what would change, but commit nothing.')
def import_admin_divisions(path, dry_run):
    """Import the Province → Commandery → County → leaf hierarchy from a
    CSV file (default data/3k_admin_divisions.csv).

    The CSV is denormalised — every row carries its full ancestor chain
    (province, commandery, county, col4). The command walks it in four
    passes (top-down) so each child's parent already exists when we get
    to it. Names are canonicalised on insert:

      column 1 → "<en> Province"
      column 2 → "<en> Commandery"
      column 3 → "<en> County"
      column 4 → raw English portion (incl. any "(town)" / "(city)" /
                  "(pass)" parenthetical), with location_type inferred
                  when the marker is recognisable.

    The Chinese portion of each cell goes into Location.chinese_name.

    Idempotent. Existing locations matched by English name (preferred)
    or chinese_name (fallback) are reused — chinese_name, location_type,
    and parent are filled in on the existing row when currently empty,
    but already-set values are never overwritten."""
    if not os.path.isfile(path):
        print(f"CSV not found: {path}")
        sys.exit(1)

    type_by_name = {t.name: t for t in LocationType.query.all()}
    required_types = {'Province', 'Commandery', 'County'}
    missing = required_types - type_by_name.keys()
    if missing:
        print(f"Missing required LocationType rows: {sorted(missing)}.")
        print("Run `flask seed-location-types` first.")
        sys.exit(1)

    # Indices over the existing data. first-wins for the same-name-twice
    # case — historical commanderies that appear under two provinces
    # get a single Location and the second CSV row reuses it.
    existing = Location.query.filter(Location.is_deleted.is_(False)).all()
    by_name = {}
    by_chinese = {}
    for l in existing:
        if l.name:
            by_name.setdefault(l.name, l)
        if l.chinese_name:
            by_chinese.setdefault(l.chinese_name, l)

    stats = {'created': 0, 'updated': 0, 'unchanged': 0}

    def _add_alias(current_csv, new_alias):
        """Merge `new_alias` into a comma-delimited aliases string,
        preserving every entry that's already there. Returns
        (joined_csv, changed). Idempotent — if the alias is already
        present (whitespace-trimmed match), nothing changes."""
        if not new_alias:
            return current_csv or '', False
        parts = [p.strip() for p in (current_csv or '').split(',') if p.strip()]
        if new_alias in parts:
            return current_csv or '', False
        parts.append(new_alias)
        return ','.join(parts), True

    def find_or_create(canonical_name, chinese, type_name, parent, alias=None):
        """Return (location, status) where status is 'created' / 'updated'
        / 'unchanged'. Looks up by English name first, falls back to
        Chinese. Fills in missing chinese_name / type / parent on
        existing rows; never overwrites values already present.

        If `alias` is given (typically the bare English name without
        any "Province"/"Commandery"/"County" suffix), it's merged into
        the location's comma-delimited `aliases` field. Idempotent —
        existing alias entries stay intact, only missing ones are
        appended. Lets the book parser match either the full canonical
        name ("Bing Province") or the bare form ("Bing")."""
        loc_type_obj = type_by_name.get(type_name) if type_name else None
        existing_row = by_name.get(canonical_name)
        if existing_row is None and chinese:
            existing_row = by_chinese.get(chinese)

        if existing_row is None:
            initial_aliases = alias if alias else ''
            loc = Location(
                name=canonical_name,
                chinese_name=chinese or '',
                aliases=initial_aliases,
            )
            if loc_type_obj is not None:
                loc.location_type = loc_type_obj
            if parent is not None:
                loc.parent = parent
            db.session.add(loc)
            by_name.setdefault(canonical_name, loc)
            if chinese:
                by_chinese.setdefault(chinese, loc)
            return loc, 'created'

        changed = False
        if not existing_row.chinese_name and chinese:
            existing_row.chinese_name = chinese
            by_chinese.setdefault(chinese, existing_row)
            changed = True
        if existing_row.location_type_id is None and loc_type_obj is not None:
            existing_row.location_type = loc_type_obj
            changed = True
        if existing_row.parent_id is None and parent is not None:
            existing_row.parent = parent
            changed = True
        if alias:
            merged, alias_changed = _add_alias(existing_row.aliases, alias)
            if alias_changed:
                existing_row.aliases = merged
                changed = True

        # Cache under both keys so later passes find this row by either
        # the canonical-suffix name OR the chinese name.
        by_name.setdefault(canonical_name, existing_row)
        if existing_row.chinese_name:
            by_chinese.setdefault(existing_row.chinese_name, existing_row)

        return existing_row, ('updated' if changed else 'unchanged')

    def _bump(status):
        stats[status] = stats.get(status, 0) + 1

    with open(path, newline='') as fh:
        rows = list(_csv.DictReader(fh))
    print(f"loaded {len(rows)} rows from {path}")

    # Pass 1 — provinces.
    provinces = {}   # raw col-1 cell -> Location
    for row in rows:
        cell = row.get('province', '').strip()
        if not cell or cell in provinces:
            continue
        en, zh = _split_en_zh(cell)
        if not en:
            continue
        loc, status = find_or_create(f"{en} Province", zh, 'Province', None, alias=en)
        _bump(status)
        provinces[cell] = loc
    db.session.flush()

    # Pass 2 — commanderies.
    commanderies = {}   # (province_cell, commandery_cell) -> Location
    for row in rows:
        prov_cell = row.get('province', '').strip()
        com_cell = row.get('commandery', '').strip()
        if not com_cell:
            continue
        key = (prov_cell, com_cell)
        if key in commanderies:
            continue
        en, zh = _split_en_zh(com_cell)
        if not en:
            continue
        parent = provinces.get(prov_cell)
        loc, status = find_or_create(f"{en} Commandery", zh, 'Commandery', parent, alias=en)
        _bump(status)
        commanderies[key] = loc
    db.session.flush()

    # Pass 3 — counties.
    counties = {}   # (prov, com, cnty) -> Location
    for row in rows:
        prov_cell = row.get('province', '').strip()
        com_cell = row.get('commandery', '').strip()
        cnty_cell = row.get('county', '').strip()
        if not cnty_cell:
            continue
        key = (prov_cell, com_cell, cnty_cell)
        if key in counties:
            continue
        en, zh = _split_en_zh(cnty_cell)
        if not en:
            continue
        parent = commanderies.get((prov_cell, com_cell))
        loc, status = find_or_create(f"{en} County", zh, 'County', parent, alias=en)
        _bump(status)
        counties[key] = loc
    db.session.flush()

    # Pass 4 — column 4 (city/town/pass/village/...).
    # Name is the raw English portion of the cell, with any trailing
    # "(town)" / "(city)" / "(pass)" type marker dropped — that info
    # lives in location_type_id, not the name. So "Qiaomen 橋門 (town)"
    # ends up as name="Qiaomen" with location_type=Settlement.
    for row in rows:
        prov_cell = row.get('province', '').strip()
        com_cell = row.get('commandery', '').strip()
        cnty_cell = row.get('county', '').strip()
        leaf_cell = row.get('city', '').strip()
        if not leaf_cell:
            continue
        en, zh = _split_en_zh(leaf_cell)
        if not en:
            continue
        # Strip "(type)" markers from the name BEFORE we look it up so
        # find_or_create matches against the same canonical form we'd
        # produce on a re-run. _detect_col4_type_name still reads the
        # original cell (it needs the parenthetical to map to a type).
        type_name = _detect_col4_type_name(leaf_cell)
        en = ' '.join(_COL4_PAREN_RE.sub('', en).split())
        if not en:
            continue
        # Pick the deepest ancestor available in this row. The schema is
        # permissive about parent type — a (town) without a county can
        # parent straight to the commandery.
        parent = (counties.get((prov_cell, com_cell, cnty_cell))
                  or commanderies.get((prov_cell, com_cell))
                  or provinces.get(prov_cell))
        loc, status = find_or_create(en, zh, type_name, parent)
        _bump(status)

    if dry_run:
        db.session.rollback()
        print("\n[dry run — nothing committed]")
    else:
        db.session.commit()

    total = sum(stats.values())
    print(
        f"\n{total} entr{'y' if total == 1 else 'ies'} touched: "
        f"{stats.get('created', 0)} created, "
        f"{stats.get('updated', 0)} updated, "
        f"{stats.get('unchanged', 0)} unchanged."
    )


@app.cli.command()
@click.argument('email')
def make_admin(email):
    """Promote the user with the given email to administrator (and mark
    them confirmed). Useful for bootstrapping the first admin."""
    user = User.query.filter_by(email=email.lower()).first()
    if user is None:
        print(f"No user with email {email!r}.")
        sys.exit(1)
    user.is_administrator = True
    user.confirmed = True
    db.session.add(user)
    db.session.commit()
    print(f"Promoted {user.username} ({user.email}) to admin.")


@app.cli.command()
@click.argument('email')
@click.argument('username')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True,
              help='Password for the new user (prompted if not provided).')
@click.option('--admin/--no-admin', default=False, help='Mark the user as administrator.')
def create_user(email, username, password, admin):
    """Create a new user (mainly for bootstrapping the first admin)."""
    if User.query.filter_by(email=email.lower()).first():
        print(f"Email {email!r} is already registered.")
        sys.exit(1)
    if User.query.filter_by(username=username).first():
        print(f"Username {username!r} is already in use.")
        sys.exit(1)

    user = User(
        email=email.lower(),
        username=username,
        confirmed=True,
        is_administrator=admin,
    )
    user.password = password
    db.session.add(user)
    db.session.commit()
    print(f"Created {user.username} ({user.email})" + (" [admin]" if admin else "") + ".")

@app.cli.command()
@click.option('--dry-run/--no-dry-run', default=False,
              help='Print what would change without writing it.')
def backfill_association_keywords(dry_run):
    """Seed per-association keyword columns from the entity's global aliases.

    The 0012 migration adds an empty `keywords` column to chapter_character,
    event_chapter, and chapter_location. This command walks every row whose
    keywords are still empty and seeds them with the corresponding entity's
    `name + aliases` (whitespace-stripped, comma-delimited, no leading
    space). Rows already populated (by admin edits via the association
    pages) are left alone. Safe to re-run.

    For Character: keywords = "name,courtesy_name,alias1,alias2,…"
    For Event:     keywords = "name,alias1,alias2,…"
    For Location:  keywords = "name,alias1,alias2,…"

    With --dry-run the command prints a summary without writing.
    """
    from sqlalchemy import text
    from app.models import Event, Location
    from app.models.character import Character as CharacterModel

    def _build(name, *extras):
        """Build a clean comma-delimited keyword string from a name +
        N extra fields (each potentially a comma-delimited string itself).
        Dedups, strips whitespace, drops empties."""
        seen = set()
        out = []
        candidates = [name or '']
        for extra in extras:
            for piece in (extra or '').split(','):
                candidates.append(piece)
        for c in candidates:
            c = (c or '').strip()
            if not c or c in seen:
                continue
            seen.add(c)
            out.append(c)
        return ','.join(out)

    plans = []   # (label, sql, params)
    updated_total = 0

    # ---- chapter_character (name + courtesy_name + aliases) -----------
    rows = db.session.execute(text("""
        SELECT cc.chapter_id, cc.character_id, c.name, c.courtesty_name, c.aliases
        FROM chapter_character cc
        JOIN character c ON c.id = cc.character_id
        WHERE cc.keywords = ''
    """)).all()
    print(f"chapter_character: {len(rows)} row(s) with empty keywords")
    for chapter_id, character_id, name, courtesy, aliases in rows:
        kw = _build(name, courtesy, aliases)
        plans.append((
            f"character({character_id}) ↔ chapter({chapter_id})",
            "UPDATE chapter_character SET keywords = :kw "
            "WHERE chapter_id = :cid AND character_id = :charid",
            {'kw': kw, 'cid': chapter_id, 'charid': character_id},
        ))

    # ---- event_chapter (name + aliases) -------------------------------
    rows = db.session.execute(text("""
        SELECT ec.event_id, ec.chapter_id, e.name, e.aliases
        FROM event_chapter ec
        JOIN event e ON e.id = ec.event_id
        WHERE ec.keywords = ''
    """)).all()
    print(f"event_chapter:     {len(rows)} row(s) with empty keywords")
    for event_id, chapter_id, name, aliases in rows:
        kw = _build(name, aliases)
        plans.append((
            f"event({event_id}) ↔ chapter({chapter_id})",
            "UPDATE event_chapter SET keywords = :kw "
            "WHERE event_id = :eid AND chapter_id = :cid",
            {'kw': kw, 'eid': event_id, 'cid': chapter_id},
        ))

    # ---- chapter_location (name + aliases) ----------------------------
    rows = db.session.execute(text("""
        SELECT cl.chapter_id, cl.location_id, l.name, l.aliases
        FROM chapter_location cl
        JOIN location l ON l.id = cl.location_id
        WHERE cl.keywords = ''
    """)).all()
    print(f"chapter_location:  {len(rows)} row(s) with empty keywords")
    for chapter_id, location_id, name, aliases in rows:
        kw = _build(name, aliases)
        plans.append((
            f"location({location_id}) ↔ chapter({chapter_id})",
            "UPDATE chapter_location SET keywords = :kw "
            "WHERE chapter_id = :cid AND location_id = :lid",
            {'kw': kw, 'cid': chapter_id, 'lid': location_id},
        ))

    if not plans:
        print("Nothing to backfill — every association row already has keywords set.")
        return

    print(f"\nTotal planned updates: {len(plans)}")
    if dry_run:
        print("\n(dry-run) Showing first 10 planned updates:")
        for label, _, params in plans[:10]:
            print(f"  {label}  ->  {params['kw']!r}")
        if len(plans) > 10:
            print(f"  … and {len(plans) - 10} more")
        return

    for _, sql, params in plans:
        db.session.execute(text(sql), params)
        updated_total += 1
    db.session.commit()
    print(f"\nDone. Updated {updated_total} association row(s).")


@app.cli.command()
@click.argument('chapter_num', type=int)
def dump_chapter_triage(chapter_num):
    """Dump every tagged association in a chapter as JSON for LLM triage.

    Read-only. Emits one JSON document to stdout containing:
      - chapter.{num, name}
      - chapter.prose                (stripped-HTML, full text)
      - matches[]: one entry per (entity, snippet) currently tagged, with
            entity {type, id, name, type_label, via, needles, candidates}
            snippet {match, before, after}
        where `via` is 'm2m' for a direct chapter_X association or
        'event:<event name>' for a location pulled in by an event's
        location FK, and `candidates` lists OTHER entities (id+name+type)
        that share at least one of this entity's chapter-scoped needles
        — used by the triage layer to suggest swap targets.

    Designed to be piped to a file or pasted into an LLM context. Safe
    to run in any environment: no writes, no network."""
    import json as _json
    from app.models.chapter import Chapter as ChapterModel
    from tools.book_parser import (
        find_location_mentions, find_character_mentions, find_event_mentions,
        load_chapter_keywords, split_keywords_csv, load_match_exclusions,
        strip_html_tags, location_needles, find_shared_needle_ids,
    )

    ch = ChapterModel.query.filter_by(chapter_num=chapter_num).first()
    if ch is None:
        raise click.ClickException(f"No chapter with chapter_num={chapter_num}")

    loc_kw = load_chapter_keywords(ch.id, 'chapter_location', 'location_id')
    char_kw = load_chapter_keywords(ch.id, 'chapter_character', 'character_id')
    event_kw = load_chapter_keywords(ch.id, 'event_chapter', 'event_id')

    # Build the same union the chapter view does so 'via' attribution
    # matches what the user sees in the sidebar.
    direct_loc_ids = {l.id for l in ch.locations}
    event_pinned = {}
    for e in ch.events:
        if e.location_id and e.location and not e.location.is_deleted:
            event_pinned.setdefault(e.location_id, e.name)
    seen_loc = set()
    locs = []
    for loc in [*(e.location for e in ch.events if e.location), *ch.locations]:
        if loc is None or loc.id in seen_loc or loc.is_deleted:
            continue
        seen_loc.add(loc.id)
        locs.append(loc)

    chars = [c for c in ch.characters if not c.is_deleted]
    events = sorted(ch.events, key=lambda e: e.name)

    def _loc_needles(loc):
        return (split_keywords_csv(loc_kw.get(loc.id, ''))
                or location_needles(loc))
    def _char_needles(c):
        return (split_keywords_csv(char_kw.get(c.id, ''))
                or c.get_all_name_labels())
    def _event_needles(e):
        from tools.book_parser import get_event_labels
        return (split_keywords_csv(event_kw.get(e.id, ''))
                or get_event_labels(e))

    # Per-entity disambiguation fields. Used both on the main entity
    # entry AND on each `candidates` row so an LLM (or human) can tell
    # two Zhang Jis / Wuchengs apart without a second round-trip.
    def _walk_ancestry(loc):
        chain, seen, cur, depth = [], set(), loc.parent, 0
        while cur is not None and cur.id not in seen and depth < 10:
            chain.append(cur.name)
            seen.add(cur.id)
            cur = cur.parent
            depth += 1
        return chain  # closest parent first

    def _urls(entity):
        return [
            {
                'url': u.url,
                'type': u.url_type.name if u.url_type else None,
                'label': u.name or None,
            }
            for u in (entity.urls or [])
            if not u.is_deleted
        ]

    def _chapter_nums(entity):
        # Sorted list of chapter_nums the entity is tagged in. The
        # cleanest disambiguator for same-name records — if one Zhang Ji
        # has [9,10,13,14] and the other has [82,90], they're not the
        # same person.
        return sorted({c.chapter_num for c in (entity.chapters or [])
                       if not c.is_deleted})

    def _character_facts(c):
        return {
            'is_fictional': bool(c.is_fictional),
            'chinese_name': c.chinese_name or None,
            # NB: column is misspelled `courtesty_name` in the schema
            # (see ISSUES.md #19) — exposing it under the corrected key
            # in JSON so consumers don't propagate the typo.
            'courtesy_name': c.courtesty_name or None,
            'chinese_courtesy_name': c.chinese_courtesty_name or None,
            'birth_date': c.birth_date or None,
            'death_date': c.death_date or None,
            'ancestral_home': c.ancestral_home or None,
            'book_mention_count': c.book_mention_count,
            'aliases': c.aliases or None,
            'roles': [r.name for r in c.roles],
            'factions': [f.name for f in c.factions.all()],
            'primary_faction': c.primary_faction.name if c.primary_faction else None,
            'tagged_in_chapters': _chapter_nums(c),
            # `links` (Character.links → Link table) deliberately
            # omitted: the link table in prod is missing the
            # created_by/last_edited_by columns the ORM expects, so
            # any lazy-load explodes. Track this in ISSUES.md as a
            # migration gap.
            'urls': _urls(c),
            'notes': c.notes or None,
        }

    def _location_facts(loc):
        return {
            'chinese_name': loc.chinese_name or None,
            'aliases': loc.aliases or None,
            'ancestry': _walk_ancestry(loc),  # closest parent first; reverse for root->leaf
            'latitude': loc.latitude,
            'longitude': loc.longitude,
            'tagged_in_chapters': _chapter_nums(loc),
            'urls': _urls(loc),
            'notes': loc.notes or None,
        }

    def _event_facts(e):
        return {
            'chinese_name': e.chinese_name or None,
            'aliases': e.aliases or None,
            'date': e.date or None,
            'location_name': e.location.name if e.location else None,
            'tagged_in_chapters': _chapter_nums(e),
            'urls': _urls(e),
            'notes': e.notes or None,
        }

    # Candidate swaps: any other entity (same type) sharing a needle.
    # Carries the full disambiguation facts so two same-name records
    # are distinguishable at a glance.
    def _candidates(entity, all_entities, needles_for, kind):
        my_needles = set(needles_for(entity))
        out = []
        for other in all_entities:
            if other.id == entity.id:
                continue
            if my_needles & set(needles_for(other)):
                ot = (other.location_type.name
                      if hasattr(other, 'location_type') and other.location_type
                      else (other.event_type.name
                            if hasattr(other, 'event_type') and other.event_type
                            else ''))
                row = {'id': other.id, 'name': other.name, 'type_label': ot}
                if kind == 'character':
                    row['facts'] = _character_facts(other)
                elif kind == 'location':
                    row['facts'] = _location_facts(other)
                elif kind == 'event':
                    row['facts'] = _event_facts(other)
                out.append(row)
        return out

    matches = []

    def _zero_match_entry(kind, entity, type_label, needles, via, facts, cand):
        """Placeholder match row for an entity that's M2M'd to the chapter
        but produces ZERO live snippets after exclusions / needle filtering.
        Without this the triage layer has no signal that an orphan
        association exists — every reader of the dump should also see
        the dead M2M rows so they can be removed."""
        return {
            'entity_type': kind,
            'entity_id': entity.id,
            'entity_name': entity.name,
            'type_label': type_label,
            'via': via,
            'needles': needles,
            'facts': facts,
            'candidates': cand,
            'snippet': None,
            'zero_matches': True,
        }

    for loc in locs:
        excl = load_match_exclusions(ch.id, 'location', loc.id)
        needles = _loc_needles(loc)
        mentions = find_location_mentions(ch, loc, limit=None,
                                          exclusions=excl, needles=needles)
        via = 'm2m' if loc.id in direct_loc_ids else f'event:{event_pinned.get(loc.id, "?")}'
        cand = _candidates(loc, locs, _loc_needles, 'location')
        facts = _location_facts(loc)
        type_label = loc.location_type.name if loc.location_type else None
        if not mentions:
            matches.append(_zero_match_entry(
                'location', loc, type_label, needles, via, facts, cand,
            ))
            continue
        for m in mentions:
            matches.append({
                'entity_type': 'location',
                'entity_id': loc.id,
                'entity_name': loc.name,
                'type_label': type_label,
                'via': via,
                'needles': needles,
                'facts': facts,
                'candidates': cand,
                'snippet': {'match': m['match'], 'before': m['before'], 'after': m['after']},
            })

    for c in chars:
        excl = load_match_exclusions(ch.id, 'character', c.id)
        needles = _char_needles(c)
        mentions = find_character_mentions(ch, c, limit=None,
                                           exclusions=excl, needles=needles)
        cand = _candidates(c, chars, _char_needles, 'character')
        facts = _character_facts(c)
        if not mentions:
            matches.append(_zero_match_entry(
                'character', c, None, needles, 'm2m', facts, cand,
            ))
            continue
        for m in mentions:
            matches.append({
                'entity_type': 'character',
                'entity_id': c.id,
                'entity_name': c.name,
                'type_label': None,
                'via': 'm2m',
                'needles': needles,
                'facts': facts,
                'candidates': cand,
                'snippet': {'match': m['match'], 'before': m['before'], 'after': m['after']},
            })

    for e in events:
        if e.is_deleted:
            continue
        excl = load_match_exclusions(ch.id, 'event', e.id)
        needles = _event_needles(e)
        mentions = find_event_mentions(ch, e, limit=None,
                                       exclusions=excl, needles=needles)
        cand = _candidates(e, events, _event_needles, 'event')
        facts = _event_facts(e)
        type_label = e.event_type.name if e.event_type else None
        if not mentions:
            matches.append(_zero_match_entry(
                'event', e, type_label, needles, 'm2m', facts, cand,
            ))
            continue
        for m in mentions:
            matches.append({
                'entity_type': 'event',
                'entity_id': e.id,
                'entity_name': e.name,
                'type_label': type_label,
                'via': 'm2m',
                'needles': needles,
                'facts': facts,
                'candidates': cand,
                'snippet': {'match': m['match'], 'before': m['before'], 'after': m['after']},
            })

    payload = {
        'chapter': {
            'num': ch.chapter_num,
            'name': ch.name,
            'prose': strip_html_tags(ch.content or ''),
        },
        'matches': matches,
    }
    click.echo(_json.dumps(payload, ensure_ascii=False, indent=2))


@app.cli.command()
@click.argument('decisions_file', type=click.Path(exists=True, dir_okay=False))
@click.option('--apply/--dry-run', default=False,
              help='Default is dry-run (prints what would happen). Pass --apply to write.')
@click.option('--no-confirm', is_flag=True, default=False,
              help='Skip the interactive confirm before --apply writes (for scripted use).')
def apply_triage_decisions(decisions_file, apply, no_confirm):
    """Apply a batch of per-snippet exclusions / M2M removals from a JSON
    file produced by `dump-chapter-triage` triage.

    Saves a ton of clicking when triage produces ~50+ per-chapter actions.
    Idempotent: exclude is skipped if the (chapter, target, fingerprint)
    row already exists; remove_m2m is a no-op if the association
    already isn't there. The same audit ORM hooks the admin pages use
    stamp `created_by` / `last_edited_by` on the new rows.

    Input file schema:

        {
          "chapter_num": 10,
          "decisions": [
            {"target_type": "location", "target_id": 62,
             "action": "exclude",
             "match_text": "Yu",
             "before_snippet": "...", "after_snippet": "..."},
            {"target_type": "location", "target_id": 1456,
             "action": "remove_m2m"},
            ...
          ]
        }

    Valid `action`s:
      - exclude    : add MatchExclusion (needs match_text + before/after)
      - restore    : delete MatchExclusion matching that fingerprint
      - remove_m2m : drop the chapter↔target association

    Valid `target_type`s: 'character', 'location', 'event'.

    Default is dry-run: prints every action with current/proposed state
    and exits without writes. Pass --apply (plus the y/N confirm, or
    --no-confirm) to actually write. Removals trigger a stronger prompt
    because they delete association rows."""
    import json as _json
    from app.models import Chapter, MatchExclusion, Location, Event
    from app.models.character import Character as CharacterModel

    payload = _json.loads(open(decisions_file).read())
    chapter_num = payload.get('chapter_num')
    decisions = payload.get('decisions') or []
    if chapter_num is None:
        raise click.ClickException("Input file missing top-level 'chapter_num'.")

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first()
    if chapter is None:
        raise click.ClickException(f"No chapter with chapter_num={chapter_num}.")

    target_models = {
        'character': CharacterModel,
        'location': Location,
        'event': Event,
    }
    m2m_attr = {
        'character': 'characters',
        'location': 'locations',
        'event': 'events',
    }

    # First pass: validate + classify into buckets so we can report
    # cleanly and confirm removals separately.
    plan = []
    for i, d in enumerate(decisions):
        ttype = d.get('target_type')
        tid = d.get('target_id')
        action = d.get('action')
        if ttype not in target_models:
            raise click.ClickException(f"decision[{i}]: bad target_type {ttype!r}")
        if action not in ('exclude', 'restore', 'remove_m2m'):
            raise click.ClickException(f"decision[{i}]: bad action {action!r}")
        target = target_models[ttype].query.get(tid)
        if target is None:
            raise click.ClickException(f"decision[{i}]: no {ttype} with id={tid}")
        entry = {'ttype': ttype, 'target': target, 'action': action}
        if action in ('exclude', 'restore'):
            match_text = (d.get('match_text') or '').strip()
            before = d.get('before_snippet') or ''
            after = d.get('after_snippet') or ''
            if not match_text:
                raise click.ClickException(
                    f"decision[{i}]: {action} needs non-empty match_text"
                )
            entry.update({
                'match_text': match_text,
                'before_snippet': before,
                'after_snippet': after,
            })
        plan.append(entry)

    # Pre-compute proposed status (would-create / would-delete / no-op).
    excl_creates = []
    excl_skips = []
    rest_deletes = []
    rest_skips = []
    m2m_removes = []
    m2m_skips = []

    for p in plan:
        ttype, target, action = p['ttype'], p['target'], p['action']
        if action == 'exclude':
            existing = MatchExclusion.query.filter_by(
                chapter_id=chapter.id,
                target_type=ttype,
                target_id=target.id,
                match_text=p['match_text'],
                before_snippet=p['before_snippet'],
                after_snippet=p['after_snippet'],
            ).first()
            (excl_skips if existing else excl_creates).append(p)
        elif action == 'restore':
            existing = MatchExclusion.query.filter_by(
                chapter_id=chapter.id,
                target_type=ttype,
                target_id=target.id,
                match_text=p['match_text'],
                before_snippet=p['before_snippet'],
                after_snippet=p['after_snippet'],
            ).first()
            if existing:
                p['_existing_id'] = existing.id
                rest_deletes.append(p)
            else:
                rest_skips.append(p)
        elif action == 'remove_m2m':
            coll = getattr(chapter, m2m_attr[ttype])
            (m2m_removes if target in coll else m2m_skips).append(p)

    click.echo(f"Chapter {chapter.chapter_num}: {chapter.name}")
    click.echo(f"  exclude   create:{len(excl_creates)} skip-existing:{len(excl_skips)}")
    click.echo(f"  restore   delete:{len(rest_deletes)} skip-missing:{len(rest_skips)}")
    click.echo(f"  remove_m2m drop:{len(m2m_removes)} skip-absent:{len(m2m_skips)}")
    click.echo()

    def _line(p, verb):
        target = p['target']
        s = f"  {verb} {p['ttype']} [{target.id}] {target.name}"
        if 'match_text' in p:
            s += f"  match={p['match_text']!r}"
        return s

    for p in excl_creates: click.echo(_line(p, 'EXCLUDE'))
    for p in rest_deletes: click.echo(_line(p, 'RESTORE'))
    for p in m2m_removes:  click.echo(_line(p, 'REMOVE-M2M'))

    if not apply:
        click.echo("\n(dry-run; pass --apply to write)")
        return

    if (m2m_removes or rest_deletes) and not no_confirm:
        # Removal-class actions get the harder prompt because they
        # delete association rows (per user's deletion-confirm rule).
        if not click.confirm(
            f"\n{len(m2m_removes)} M2M removal(s) and {len(rest_deletes)} "
            f"exclusion-restore(s) will be applied. Continue?",
            default=False,
        ):
            click.echo("Aborted; nothing written.")
            return
    elif not no_confirm and excl_creates:
        if not click.confirm(
            f"\n{len(excl_creates)} exclusion(s) will be written. Continue?",
            default=True,
        ):
            click.echo("Aborted; nothing written.")
            return

    # Apply.
    written_excl = 0
    deleted_excl = 0
    removed_m2m = 0
    for p in excl_creates:
        db.session.add(MatchExclusion(
            chapter_id=chapter.id,
            target_type=p['ttype'],
            target_id=p['target'].id,
            match_text=p['match_text'],
            before_snippet=p['before_snippet'],
            after_snippet=p['after_snippet'],
        ))
        written_excl += 1
    for p in rest_deletes:
        row = MatchExclusion.query.get(p['_existing_id'])
        if row:
            db.session.delete(row)
            deleted_excl += 1
    for p in m2m_removes:
        getattr(chapter, m2m_attr[p['ttype']]).remove(p['target'])
        removed_m2m += 1

    db.session.commit()
    click.echo(
        f"\nWrote {written_excl} exclusion(s), deleted {deleted_excl}, "
        f"removed {removed_m2m} M2M association(s)."
    )


@app.cli.command()
@click.argument('start', type=int)
@click.argument('end', type=int, required=False)
def dump_chapters_for_dating(start, end):
    """Dump chapter prose + dated context as JSON for LLM-assisted dating.

    For each chapter in [start, end] (or just `start` if `end` omitted),
    emits an object with:
      - chapter_num, name, current_date
      - prev_chapter / next_chapter {num, name, date}     (context)
      - prose                                              (HTML-stripped)
      - dated_characters[]: tagged characters that have a birth or
        death date set — likely anchors for the chapter year
      - dated_events[]: tagged events that have a date set

    Output is a JSON array on stdout. Pipe to a file and share with
    the dating workflow (mirrors how `dump-chapter-triage` feeds the
    triage workflow). Read-only — no writes."""
    import json as _json
    from app.models.chapter import Chapter as ChapterModel
    from tools.book_parser import strip_html_tags

    if end is None:
        end = start
    if end < start:
        raise click.ClickException(f"end ({end}) must be >= start ({start})")

    chapters = (
        ChapterModel.query
        .filter(ChapterModel.chapter_num >= start)
        .filter(ChapterModel.chapter_num <= end)
        .order_by(ChapterModel.chapter_num)
        .all()
    )
    by_num = {c.chapter_num: c for c in ChapterModel.query.order_by(ChapterModel.chapter_num).all()}

    out = []
    for ch in chapters:
        prev_ch = by_num.get(ch.chapter_num - 1)
        next_ch = by_num.get(ch.chapter_num + 1)

        dated_chars = []
        for c in sorted(ch.characters or [], key=lambda x: x.name):
            if c.is_deleted:
                continue
            if not (c.birth_date or c.death_date):
                continue
            dated_chars.append({
                'name': c.name,
                'chinese_name': c.chinese_name or '',
                'birth_date': c.birth_date or '',
                'death_date': c.death_date or '',
            })

        dated_events = []
        for e in sorted(ch.events or [], key=lambda x: x.name):
            if e.is_deleted or not e.date:
                continue
            dated_events.append({
                'name': e.name,
                'date': e.date,
            })

        out.append({
            'chapter_num': ch.chapter_num,
            'name': ch.name or '',
            'current_date': ch.date or '',
            'prev_chapter': {
                'num': prev_ch.chapter_num,
                'name': prev_ch.name or '',
                'date': prev_ch.date or '',
            } if prev_ch else None,
            'next_chapter': {
                'num': next_ch.chapter_num,
                'name': next_ch.name or '',
                'date': next_ch.date or '',
            } if next_ch else None,
            'dated_characters': dated_chars,
            'dated_events': dated_events,
            'prose': strip_html_tags(ch.content or ''),
        })

    click.echo(_json.dumps(out, ensure_ascii=False, indent=2))


@app.cli.command()
@click.option('--type', 'type_filter', default=None,
              help='Only dump locations whose LocationType.name matches '
                   '(e.g. Province, Commandery). Case-insensitive.')
def dump_locations(type_filter):
    """Dump every active Location as a JSON array on stdout.

    Output per row:
      - id, name, chinese_name, aliases, notes
      - type: LocationType.name (or null)
      - parent_chain: ["Hebei Province", "Zhongshan Commandery", ...]
      - latitude, longitude            (may be null)
      - has_geojson                    (true/false — full polygon
                                        omitted to keep the dump small)

    Pipe to a file and share with the mapping workflow (mirrors
    `dump-chapters-for-dating`). Read-only — no writes."""
    import json as _json
    from app.models import Location, LocationType

    q = (
        Location.query
        .filter(Location.is_deleted.is_(False))
        .order_by(Location.name)
    )
    if type_filter:
        q = (
            q.join(LocationType, Location.location_type_id == LocationType.id)
             .filter(db.func.lower(LocationType.name) == type_filter.lower())
        )

    rows = q.all()

    # Build a parent map once so each row's parent_chain is a single
    # walk, not N queries.
    all_active = {l.id: l for l in Location.query.filter(Location.is_deleted.is_(False)).all()}

    def parent_chain(loc):
        chain = []
        seen = set()
        cur = loc.parent_id and all_active.get(loc.parent_id)
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            chain.append(cur.name)
            cur = cur.parent_id and all_active.get(cur.parent_id)
        return chain

    out = []
    for loc in rows:
        out.append({
            'id': loc.id,
            'name': loc.name or '',
            'chinese_name': loc.chinese_name or '',
            'aliases': loc.aliases or '',
            'notes': loc.notes or '',
            'type': loc.location_type.name if loc.location_type else None,
            'parent_chain': parent_chain(loc),
            'latitude': loc.latitude,
            'longitude': loc.longitude,
            'has_geojson': loc.geojson is not None,
        })

    click.echo(_json.dumps(out, ensure_ascii=False, indent=2))


@app.cli.command()
@click.argument('decisions_file', type=click.Path(exists=True, dir_okay=False))
@click.option('--apply/--dry-run', default=False,
              help='Default is dry-run (prints what would change). Pass --apply to write.')
def apply_location_geo(decisions_file, apply):
    """Apply geo data (lat/lng points OR GeoJSON polygons) to Location rows.

    Input file is a flat JSON list. Each entry references a Location
    by id and provides EITHER a point OR a polygon (or both — the
    /map view prefers the point at render time):

        [
          {"id": 925, "latitude": 36.5, "longitude": 105.7,
           "_note": "approximate centroid, CHGIS 140 AD"},
          {"id": 1004, "geojson": {"type": "Polygon",
                                   "coordinates": [[[...], ...]]},
           "_note": "Eastern Han commandery, CHGIS v6"},
          ...
        ]

    Validation:
      - `id` must reference an existing Location (soft-deleted ones
        are rejected so accidental writes against deleted rows don't
        silently land).
      - `geojson` must be a GeoJSON Geometry object — its `type` has
        to be Polygon or MultiPolygon (Point goes via lat/lng).
      - At least one of (latitude+longitude) or geojson must be
        present.

    Idempotent: rows whose stored value already matches the proposed
    one are reported as no-ops. Default is dry-run; pass --apply to
    write. The audit hooks in app/models/audit.py stamp
    `last_edited_by` automatically."""
    import json as _json
    from app.models import Location

    payload = _json.loads(open(decisions_file).read())
    if not isinstance(payload, list):
        raise click.ClickException(
            "File must contain a JSON list of {id, ...} objects."
        )

    by_id = {
        loc.id: loc
        for loc in Location.query.filter(Location.is_deleted.is_(False)).all()
    }

    plan = []
    for i, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise click.ClickException(
                f"entry[{i}]: expected an object, got {type(entry).__name__}"
            )
        loc_id = entry.get('id')
        if not isinstance(loc_id, int):
            raise click.ClickException(f"entry[{i}]: missing/invalid 'id'")
        loc = by_id.get(loc_id)
        if loc is None:
            raise click.ClickException(
                f"entry[{i}]: no active Location with id={loc_id}"
            )

        lat = entry.get('latitude')
        lng = entry.get('longitude')
        geom = entry.get('geojson')

        has_point = lat is not None and lng is not None
        has_geom = geom is not None

        if not has_point and not has_geom:
            raise click.ClickException(
                f"entry[{i}] (id={loc_id}): provide latitude+longitude, "
                "geojson, or both"
            )

        if has_point:
            if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
                raise click.ClickException(
                    f"entry[{i}] (id={loc_id}): latitude/longitude must be numbers"
                )
        if has_geom:
            if not isinstance(geom, dict):
                raise click.ClickException(
                    f"entry[{i}] (id={loc_id}): geojson must be an object"
                )
            if geom.get('type') not in ('Polygon', 'MultiPolygon'):
                raise click.ClickException(
                    f"entry[{i}] (id={loc_id}): geojson.type must be Polygon "
                    "or MultiPolygon (got {!r})".format(geom.get('type'))
                )
            if not isinstance(geom.get('coordinates'), list):
                raise click.ClickException(
                    f"entry[{i}] (id={loc_id}): geojson.coordinates must be a list"
                )

        plan.append({
            'loc': loc,
            'new_lat': float(lat) if has_point else None,
            'new_lng': float(lng) if has_point else None,
            'set_point': has_point,
            'new_geom': geom if has_geom else None,
            'set_geom': has_geom,
            'note': entry.get('_note') or '',
        })

    changes = 0
    for p in plan:
        loc = p['loc']
        actions = []
        if p['set_point']:
            if loc.latitude != p['new_lat'] or loc.longitude != p['new_lng']:
                actions.append(
                    f"lat/lng {loc.latitude!r},{loc.longitude!r} -> "
                    f"{p['new_lat']},{p['new_lng']}"
                )
        if p['set_geom']:
            had = loc.geojson is not None
            if not had or loc.geojson != p['new_geom']:
                coord_count = _coord_point_count(p['new_geom'])
                actions.append(
                    f"geojson {'(replace)' if had else '(set)'} "
                    f"{p['new_geom']['type']}, {coord_count} pts"
                )
        if actions:
            changes += 1
            click.echo(
                f"  [{loc.id:>5}] {loc.name!s:35s}  " + "; ".join(actions)
                + (f"  # {p['note']}" if p['note'] else "")
            )
        else:
            click.echo(
                f"  [{loc.id:>5}] {loc.name!s:35s}  (unchanged)"
            )

    click.echo(f"\n{changes} change(s), {len(plan) - changes} no-op(s) "
               f"across {len(plan)} entry/entries.")

    if not apply:
        click.echo("\nDry-run. Pass --apply to write.")
        return

    if not changes:
        click.echo("\nNothing to change.")
        return

    for p in plan:
        loc = p['loc']
        if p['set_point']:
            loc.latitude = p['new_lat']
            loc.longitude = p['new_lng']
        if p['set_geom']:
            loc.geojson = p['new_geom']
    db.session.commit()
    click.echo(f"\nWrote {changes} Location row(s).")


def _coord_point_count(geom):
    """Count vertex points in a GeoJSON Polygon / MultiPolygon. Just
    for the dry-run report — gives a sense of polygon resolution
    without dumping the whole array."""
    coords = geom.get('coordinates') or []
    if geom.get('type') == 'Polygon':
        # coords is [[[x,y], ...], ...]  (outer ring + holes)
        return sum(len(ring) for ring in coords)
    if geom.get('type') == 'MultiPolygon':
        # coords is [[[[x,y], ...], ...], ...]
        return sum(len(ring) for poly in coords for ring in poly)
    return 0


@app.cli.command()
@click.argument('decisions_file', type=click.Path(exists=True, dir_okay=False))
@click.option('--apply/--dry-run', default=False,
              help='Default is dry-run (prints what would change). Pass --apply to write.')
def apply_chapter_dates(decisions_file, apply):
    """Apply chapter date strings from a JSON file.

    Input file schema (one flat list — keep it small, dates are tiny):

        [
          {"chapter_num": 1, "date": "184",       "_note": "Yellow Turbans rise"},
          {"chapter_num": 2, "date": "184-185",   "_note": "..."},
          ...
        ]

    `date` may be any free-form string the timeline parser accepts —
    a single year ("184"), a month + year ("February 184"), or a
    range ("184-185").  An empty string clears the chapter's date.

    Idempotent: rows whose `date` already matches the chapter are
    reported as no-ops. Default is dry-run; pass --apply to write.
    The existing audit hooks (app/models/audit.py + edit log) stamp
    the rest — no per-row plumbing needed here."""
    import json as _json

    payload = _json.loads(open(decisions_file).read())
    if not isinstance(payload, list):
        raise click.ClickException("File must contain a JSON list of {chapter_num, date} objects.")

    by_num = {c.chapter_num: c for c in Chapter.query.order_by(Chapter.chapter_num).all()}

    plan = []
    for i, entry in enumerate(payload):
        if not isinstance(entry, dict):
            raise click.ClickException(f"entry[{i}]: expected an object, got {type(entry).__name__}")
        num = entry.get('chapter_num')
        new_date = entry.get('date')
        if not isinstance(num, int):
            raise click.ClickException(f"entry[{i}]: missing/invalid 'chapter_num'")
        if not isinstance(new_date, str):
            raise click.ClickException(f"entry[{i}]: missing/invalid 'date' (must be a string)")
        ch = by_num.get(num)
        if ch is None:
            raise click.ClickException(f"entry[{i}]: no chapter with chapter_num={num}")
        new_date = new_date.strip()
        plan.append({
            'chapter': ch,
            'old_date': ch.date or '',
            'new_date': new_date,
            'note': entry.get('_note') or '',
        })

    changes = [p for p in plan if p['old_date'] != p['new_date']]
    noops = len(plan) - len(changes)

    click.echo(f"Loaded {len(plan)} chapter date assignment(s) "
               f"({len(changes)} change, {noops} no-op).\n")

    for p in plan:
        ch = p['chapter']
        if p['old_date'] == p['new_date']:
            click.echo(f"  Chapter {ch.chapter_num:>3}: {p['new_date']!r:24s}  (unchanged)")
        else:
            click.echo(
                f"  Chapter {ch.chapter_num:>3}: {p['old_date']!r:24s} -> {p['new_date']!r}"
                + (f"  # {p['note']}" if p['note'] else "")
            )

    if not apply:
        click.echo("\nDry-run. Pass --apply to write.")
        return

    if not changes:
        click.echo("\nNothing to change.")
        return

    for p in changes:
        p['chapter'].date = p['new_date']
    db.session.commit()
    click.echo(f"\nWrote {len(changes)} chapter date(s).")


@app.cli.command()
@click.option('--only', type=click.Choice(['chapter', 'event', 'character']), default=None,
              help='Restrict the report to a single source table.')
def check_date_parsing(only):
    """Report which free-form date strings the timeline parser rejects.

    Sweeps `chapter.date`, `event.date`, and `character.birth_date` /
    `character.death_date`, runs each through `tools.date_parser`, and
    prints anything that comes back None. Use this to spot which
    real-world strings the parser is missing so the patterns can be
    widened. Read-only — no writes."""
    from tools.date_parser import parse_date_range
    from app.models import Event
    sources = []
    if only in (None, 'chapter'):
        sources.append(('chapter', Chapter.query.order_by(Chapter.chapter_num).all(),
                        [('date', 'date')]))
    if only in (None, 'event'):
        sources.append(('event',
                        Event.query.filter(Event.is_deleted.is_(False)).order_by(Event.name).all(),
                        [('date', 'date')]))
    if only in (None, 'character'):
        sources.append(('character',
                        Character.query.filter(Character.is_deleted.is_(False)).order_by(Character.name).all(),
                        [('birth_date', 'birth'), ('death_date', 'death')]))

    grand_total = 0
    grand_failed = 0
    for label, rows, fields in sources:
        filled = 0
        failed = 0
        for row in rows:
            for attr, kind in fields:
                value = (getattr(row, attr) or '').strip()
                if not value:
                    continue
                filled += 1
                if parse_date_range(value) is None:
                    failed += 1
                    print(f"  [{label}/{kind}] {row.name!r:40s}  ->  {value!r}")
        grand_total += filled
        grand_failed += failed
        print(f"{label}: {filled - failed}/{filled} parsed "
              f"({failed} unparseable)")
    print(f"\nTotal: {grand_total - grand_failed}/{grand_total} parsed "
          f"({grand_failed} unparseable)")


@app.cli.command()
def deploy():
    """Run deployment tasks."""
    pass
    # migrate database to latest revision
    #upgrade()

    # create or update user roles
    #Role.insert_roles()

    # ensure all users are following themselves
    #User.add_self_follows()

# @app.shell_context_processor
# def make_shell_context():
#     return dict(db=db, User=User, Follow=Follow, Role=Role,
#                 Permission=Permission, Post=Post, Comment=Comment)


# @app.cli.command()
# @click.option('--coverage/--no-coverage', default=False,
#               help='Run tests under code coverage.')
# @click.argument('test_names', nargs=-1)
# def test(coverage, test_names):
#     """Run the unit tests."""
#     if coverage and not os.environ.get('FLASK_COVERAGE'):
#         import subprocess
#         os.environ['FLASK_COVERAGE'] = '1'
#         sys.exit(subprocess.call(sys.argv))

#     import unittest
#     if test_names:
#         tests = unittest.TestLoader().loadTestsFromNames(test_names)
#     else:
#         tests = unittest.TestLoader().discover('tests')
#     unittest.TextTestRunner(verbosity=2).run(tests)
#     if COV:
#         COV.stop()
#         COV.save()
#         print('Coverage Summary:')
#         COV.report()
#         basedir = os.path.abspath(os.path.dirname(__file__))
#         covdir = os.path.join(basedir, 'tmp/coverage')
#         COV.html_report(directory=covdir)
#         print('HTML version: file://%s/index.html' % covdir)
#         COV.erase()


# @app.cli.command()
# @click.option('--length', default=25,
#               help='Number of functions to include in the profiler report.')
# @click.option('--profile-dir', default=None,
#               help='Directory where profiler data files are saved.')
# def profile(length, profile_dir):
#     """Start the application under the code profiler."""
#     from werkzeug.contrib.profiler import ProfilerMiddleware
#     app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[length],
#                                       profile_dir=profile_dir)
#     app.run()


@app.errorhandler(403)
def forbidden(e):
    if request.accept_mimetypes.accept_json and \
            not request.accept_mimetypes.accept_html:
        response = jsonify({'error': 'forbidden'})
        response.status_code = 403
        return response
    return render_template('errors/403.html'), 403


@app.errorhandler(404)
def page_not_found(e):
    if request.accept_mimetypes.accept_json and \
            not request.accept_mimetypes.accept_html:
        response = jsonify({'error': 'not found'})
        response.status_code = 404
        return response
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    if request.accept_mimetypes.accept_json and \
            not request.accept_mimetypes.accept_html:
        response = jsonify({'error': 'internal server error'})
        response.status_code = 500
        return response
    return render_template('errors/500.html'), 500
