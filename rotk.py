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
from tools.book_parser import get_characters_for_chapter, scan_chapter_for_characters
from flask import render_template, request, jsonify
import os, time, urllib.parse

# COV = None
# if os.environ.get('FLASK_COVERAGE'):
#     import coverage
#     COV = coverage.coverage(branch=True, include='app/*')
#     COV.start()

# from flask_migrate import Migrate, upgrade
from app.models import \
    Chapter, Character, Faction, Role, User, Tag, TagAssociation
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
