import os
import re
import string
from flask import render_template, abort, request, current_app, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from app import db
from app.models import Chapter, Character, Faction, Role, Tag, TagAssociation, Url, UrlType, Location, Event
from app.models.character import Portrait, PORTRAIT_DIR
from . import main
from .forms import EditCharacterForm, EditFactionForm, EditRoleForm, \
    CharacterFilterForm, UploadPortraitForm, MergeFactionForm, AddUrlForm, \
    EditLocationForm, EditEventForm

from tools.decorators import admin_required
from tools.book_parser import get_characters_for_chapter, build_needle_pattern, build_name_ref_html, count_mentions_per_character, build_event_ref_html, build_location_ref_html, get_event_labels, get_location_labels, strip_html_tags, load_match_exclusions, normalize_snippet


def _normalize_csv(s):
    """Normalise a comma-delimited keyword list: strip whitespace around
    each entry, drop empties, rejoin with bare commas (no spaces). Keeps
    the stored format stable so "A, B" and "A,B" never live side-by-side
    in the same `aliases` column."""
    if not s:
        return ''
    return ','.join(part.strip() for part in s.split(',') if part.strip())


# Per-portrait upload cap. The WSGI-level MAX_CONTENT_LENGTH is slightly
# higher to leave room for multipart overhead; this is the post-parse limit
# we apply to the file itself.
_MAX_PORTRAIT_BYTES = 10 * 1024 * 1024  # 10 MB


def _detect_image_type(header):
    """Inspect the first ~12 bytes of an upload and return one of
    'jpg' | 'png' | 'gif' | 'webp', or None if no known image signature
    matches. Used to confirm the file's actual content matches its
    declared extension before we trust either."""
    if header.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if header[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'webp'
    return None

@main.route('/', methods=['GET'])
def index():
    chapters = Chapter.query.order_by(Chapter.chapter_num).all()

    return render_template(
        'book/table_of_contents.html',
        chapters=chapters
    )

@main.route('/chapter/<int:chapter_num>', methods=['GET'])
def chapter(chapter_num):
    from collections import defaultdict

    chapter = Chapter.query.filter(Chapter.chapter_num == chapter_num).first()

    if not chapter:
        abort(404)

    characters = get_characters_for_chapter(chapter.id)
    characters.sort(key=lambda x: x.name)

    replacements = {}
    needle_to_character_id = {}
    needle_to_location_id = {}

    # Admin-only: flag characters whose `name` is shared with another
    # character in this same chapter so the inline pill gets a red
    # circle-exclamation linking to the Character/Chapter Association
    # editor. Lets the admin spot ambiguous matches without having to
    # cross-check every name by hand.
    from collections import Counter
    is_admin = current_user.is_authenticated and current_user.is_administrator
    dup_names = {n for n, count in Counter(c.name for c in characters).items() if count > 1}
    dup_url = url_for('admin.chapter_associations', chapter_num=chapter.chapter_num) if is_admin and dup_names else None

    # Characters get first claim on a needle so character mentions never
    # get accidentally re-coloured as an event/location with the same word.
    # display_text=name_needle keeps the prose word visible in the pill
    # (e.g. "Mengde" stays "Mengde") while data-character-id still points
    # at the canonical character — so the sidebar panel + chapter-style
    # switcher / link-style behaviour resolve to the right person.
    for character in characters:
        warn_url = dup_url if (dup_url and character.name in dup_names) else None
        for name_needle in character.get_all_name_labels():
            replacements[name_needle] = build_name_ref_html(
                character,
                duplicate_warning_url=warn_url,
                display_text=name_needle,
            )
            needle_to_character_id[name_needle] = character.id

    # Events + locations get black-underlined spans linking to the
    # respective sidebar accordion item. Both pre-loaded into
    # chapter_events / chapter_locations below; building the labels now
    # so they participate in the same single regex pass.
    for event in sorted(chapter.events, key=lambda e: e.name):
        for needle in get_event_labels(event):
            if needle in replacements:
                continue   # character already claimed it
            replacements[needle] = build_event_ref_html(event, match_text=needle)

    # Locations from any source — events that pin to one + direct
    # chapter ↔ location associations. De-dup by id; first one wins.
    seen_loc_ids = set()
    locations_for_render = []
    for loc in [*(e.location for e in chapter.events if e.location), *chapter.locations]:
        if loc is None or loc.id in seen_loc_ids:
            continue
        seen_loc_ids.add(loc.id)
        locations_for_render.append(loc)
        for needle in get_location_labels(loc):
            if needle in replacements:
                continue
            replacements[needle] = build_location_ref_html(loc, match_text=needle)
            needle_to_location_id[needle] = loc.id

    pattern = build_needle_pattern(list(replacements.keys()))

    # ----- Per-snippet exclusions for locations ---------------------------
    # Admins can mark individual location matches as "wrong" on the
    # location-associations page. The exclusion fingerprints below
    # match what find_location_mentions() produces against stripped
    # chapter content. Pre-compute which (loc_id, needle, occurrence)
    # tuples should NOT get re-wrapped as inline refs; the
    # replace_match closure consults this skip-set per match.
    stripped_content = strip_html_tags(chapter.content) if needle_to_location_id else ''
    location_skip_indices = {}   # (loc_id, needle) -> set of 0-indexed match positions to skip
    for loc in locations_for_render:
        fingerprints = load_match_exclusions(chapter.id, 'location', loc.id)
        if not fingerprints:
            continue
        for needle in get_location_labels(loc):
            if needle_to_location_id.get(needle) != loc.id:
                continue  # character or earlier location already claimed this needle
            pat = build_needle_pattern([needle])
            skips = set()
            for i, m in enumerate(pat.finditer(stripped_content)):
                start, end = m.start(), m.end()
                before = stripped_content[max(0, start - 60):start]
                after = stripped_content[end:end + 60]
                if start - 60 > 0:
                    before = before.split(' ', 1)[1] if ' ' in before else before
                    before = '…' + before.lstrip()
                if end + 60 < len(stripped_content):
                    after = after.rsplit(' ', 1)[0] if ' ' in after else after
                    after = after.rstrip() + '…'
                fp = (
                    normalize_snippet(before),
                    normalize_snippet(m.group(0)),
                    normalize_snippet(after),
                )
                if fp in fingerprints:
                    skips.add(i)
            if skips:
                location_skip_indices[(loc.id, needle)] = skips

    # Count mentions per character as a side-effect of the rendering pass —
    # avoids a second scan of the chapter content for the sidebar's
    # "N mentions" badges.
    mention_counts = defaultdict(int)
    location_seen = defaultdict(int)   # (loc_id, needle) -> running counter

    def replace_match(match):
        matched = match.group(0)
        cid = needle_to_character_id.get(matched)
        if cid is not None:
            mention_counts[cid] += 1
            return replacements[matched]
        loc_id = needle_to_location_id.get(matched)
        if loc_id is not None:
            key = (loc_id, matched)
            idx = location_seen[key]
            location_seen[key] += 1
            skips = location_skip_indices.get(key)
            if skips is not None and idx in skips:
                return matched   # admin-excluded snippet → leave as plain prose
        return replacements[matched]

    rendered_content = pattern.sub(replace_match, chapter.content) if replacements else chapter.content

    # Events associated with this chapter, plus the unique set of
    # Locations — both event-pinned (from each event.location) AND
    # directly-associated (chapter ↔ location M2M via the
    # /admin/location-associations tool). Deduped by id, name-sorted.
    chapter_events = sorted(chapter.events, key=lambda e: e.name)
    locations_by_id = {
        e.location.id: e.location for e in chapter_events if e.location
    }
    for loc in chapter.locations:
        locations_by_id.setdefault(loc.id, loc)
    chapter_locations = sorted(locations_by_id.values(), key=lambda loc: loc.name)

    return render_template(
        'book/chapter.html',
        chapter=chapter,
        chapter_content=rendered_content,
        characters=characters,
        mention_counts=mention_counts,
        chapter_events=chapter_events,
        chapter_locations=chapter_locations,
    )

@main.route('/characters', methods=['GET', 'POST'])
def characters():

    letter = request.args.get("letter", "").upper()
    alphabet = alphabet = list(string.ascii_uppercase)
    page = request.args.get('page', 1, type=int)

    form = CharacterFilterForm(request.args)

    # Start with the base query
    query = Character.query

    # Apply filtering if a letter is selected
    if letter:
        query = query.filter(Character.name.startswith(letter))

    # Apply role filter
    if form.role.data:
        query = query.filter(Character.roles.any(Role.id == form.role.data.id))

    # Two independent faction filters. `any_faction` matches characters
    # whose M2M factions list contains the chosen faction (past or
    # present); `primary_faction` matches strictly on primary. Both can
    # be combined.
    if form.any_faction.data:
        query = query.filter(Character.factions.any(Faction.id == form.any_faction.data.id))
    if form.primary_faction.data:
        query = query.filter(Character.primary_faction == form.primary_faction.data)

    if form.search_query.data:
        search_term = f"%{form.search_query.data}%"
        query = query.filter(Character.name.ilike(search_term))

    # Batch-load portraits and chapters so the per-row image + chapter list
    # in the template doesn't N+1 the DB.
    query = query.options(
        selectinload(Character.portraits),
        selectinload(Character.chapters),
    )

    # Apply pagination after filtering
    pagination = query.order_by(Character.name).paginate(
        page=page,
        per_page=current_app.config['CHARACTERS_PER_PAGE'],
        error_out=False
    )

    characters = pagination.items  # Get current page items

    # Pick one image per character to show next to the row: the default if
    # set, else the first non-hidden portrait, else None. Matches the
    # ordering the chapter sidebar uses for its first tab.
    default_portraits = {}
    chapter_lists = {}
    for ch in characters:
        visible = sorted(
            (p for p in ch.portraits if not p.is_deleted and not p.is_hidden),
            key=lambda p: not p.is_default,
        )
        default_portraits[ch.id] = visible[0] if visible else None
        chapter_lists[ch.id] = sorted(
            ch.chapters, key=lambda c: c.chapter_num
        )

    return render_template(
        'characters/characters.html',
        characters=characters,
        pagination=pagination,
        page=page,
        alphabet=alphabet,
        form=form,
        letter=letter,
        default_portraits=default_portraits,
        chapter_lists=chapter_lists,
    )

@main.route('/characters/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_character():
    """Admin form to create a brand-new Character. Reuses the same template
    as the edit page, but doesn't pass `portraits` / `upload_form` so the
    images section is skipped (the character has no id yet to attach
    portraits to)."""
    from sqlalchemy.exc import IntegrityError

    form = EditCharacterForm()
    if form.validate_on_submit():
        character = Character()
        form.populate_obj(character)
        character.aliases = _normalize_csv(character.aliases)

        # Same primary_faction consistency rule as edit_character.
        if (
            character.primary_faction is not None
            and character.primary_faction not in character.factions.all()
        ):
            character.factions.append(character.primary_faction)

        db.session.add(character)
        try:
            db.session.flush()   # populate character.id for the recount step
        except IntegrityError:
            db.session.rollback()
            flash(
                f"Couldn't create {form.name.data!r}: a character with the "
                f"same name + birth/death + ancestral home already exists."
            )
            return render_template('characters/character_edit.html', form=form)

        # Fresh row → its book mention count is unknown; compute it now so
        # the chapter sidebar shows real numbers right away.
        counts = count_mentions_per_character(Chapter.query.all(), [character])
        character.book_mention_count = counts.get(character.id, 0)

        db.session.commit()
        flash(f"Created character {character.name!r}.")
        return redirect(url_for('main.edit_character', id=character.id))

    return render_template('characters/character_edit.html', form=form)


@main.route('/characters/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_character(id):
    character = Character.query.get_or_404(id)
    form = EditCharacterForm(obj=character)

    if form.validate_on_submit():
        # Capture the pre-edit labels so we can tell whether the regex-needles
        # for this character changed. If they did, the cached
        # book_mention_count is stale and we should recount before commit.
        old_labels = (character.name, character.courtesty_name, character.aliases)
        form.populate_obj(character)
        character.aliases = _normalize_csv(character.aliases)
        new_labels = (character.name, character.courtesty_name, character.aliases)

        # If a main faction is picked but isn't in the M2M factions list,
        # auto-add it so the data stays consistent (otherwise the chapter
        # sidebar would highlight a faction the character supposedly
        # isn't a member of).
        if (
            character.primary_faction is not None
            and character.primary_faction not in character.factions.all()
        ):
            character.factions.append(character.primary_faction)

        if old_labels != new_labels:
            counts = count_mentions_per_character(
                Chapter.query.all(), [character]
            )
            character.book_mention_count = counts.get(character.id, 0)

        db.session.add(character)
        db.session.commit()
        flash('The character has been updated.')
        return redirect(url_for("main.edit_character", id=character.id))

    # Admin view of the edit page surfaces hidden portraits too (with a
    # visual marker), so the admin can promote / unhide them from here
    # without bouncing to the Image Manager.
    portraits = [p for p in character.portraits if not p.is_deleted]
    portraits.sort(key=lambda p: (not p.is_default, p.is_hidden))

    upload_form = UploadPortraitForm()
    all_tags = Tag.query.order_by(Tag.name).all()
    add_url_form = AddUrlForm()
    urls = [u for u in character.urls if not u.is_deleted]

    # Bare FlaskForm gives us CSRF tokens for the per-portrait toggle forms
    # below. They POST to admin.toggle_portrait_hidden / set_default_portrait
    # which both verify the token via their own _CsrfOnlyForm instance.
    from flask_wtf import FlaskForm
    csrf_form = FlaskForm()

    return render_template(
        'characters/character_edit.html',
        form=form,
        character=character,
        portraits=portraits,
        upload_form=upload_form,
        all_tags=all_tags,
        add_url_form=add_url_form,
        urls=urls,
        csrf_form=csrf_form,
    )


@main.route('/characters/<int:id>/upload-portrait', methods=['POST'])
@login_required
@admin_required
def upload_portrait(id):
    """Manually upload an image for a character.

    Defense in depth:
      1. Admin-only (decorators).
      2. CSRF (FlaskForm).
      3. Werkzeug-level request size cap (Config.MAX_CONTENT_LENGTH).
      4. Per-file size cap re-checked here against _MAX_PORTRAIT_BYTES.
      5. Extension allow-list at the form level (FileAllowed).
      6. Magic-byte sniffing — we never trust the declared extension alone.
      7. Filename is server-constructed; user input never reaches the path.
      8. Saved path is verified to live inside PORTRAIT_DIR before write.
    """
    character = Character.query.get_or_404(id)
    form = UploadPortraitForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}")
        return redirect(url_for('main.edit_character', id=character.id))

    file = form.image_file.data
    if not file or not file.filename:
        flash("No file selected.")
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Size check ------------------------------------------------------
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size <= 0:
        flash("Uploaded file is empty.")
        return redirect(url_for('main.edit_character', id=character.id))
    if size > _MAX_PORTRAIT_BYTES:
        flash(
            f"File too large ({size:,} bytes). Max {_MAX_PORTRAIT_BYTES:,} bytes."
        )
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Magic-byte check ------------------------------------------------
    header = file.stream.read(32)
    file.stream.seek(0)
    detected = _detect_image_type(header)
    if detected is None:
        flash(
            "Uploaded file doesn't look like a real image "
            "(JPEG/PNG/GIF/WEBP signatures didn't match)."
        )
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Extension consistency ------------------------------------------
    # FileAllowed already rejected anything outside the allow-list, but we
    # also want the declared extension to match the file's actual content.
    safe_original = secure_filename(file.filename) or 'upload'
    declared_ext = os.path.splitext(safe_original)[1].lower()
    declared = 'jpg' if declared_ext == '.jpeg' else declared_ext.lstrip('.')
    if declared != detected:
        flash(
            f"File extension {declared_ext!r} doesn't match the actual "
            f"content ({detected!r}). Refusing to save."
        )
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Tag validation --------------------------------------------------
    tag_name = (form.tag_name.data or '').strip()
    if tag_name and len(tag_name) > 255:
        flash("Tag name too long (max 255 characters).")
        return redirect(url_for('main.edit_character', id=character.id))

    # ---- Build the destination path (server-constructed, never user input) ----
    portraits_dir = os.path.join(current_app.static_folder, PORTRAIT_DIR)
    os.makedirs(portraits_dir, exist_ok=True)
    final_ext = f'.{detected}'  # always sanitised; never echoes user value
    n = 0
    while True:
        suffix = f'_{n}' if n else ''
        filename = f'{character.id}_manual{suffix}{final_ext}'
        path = os.path.join(portraits_dir, filename)
        if not os.path.exists(path):
            break
        n += 1

    # Belt-and-braces: confirm the resolved path stays inside PORTRAIT_DIR
    # even if filename construction ever regresses.
    abs_path = os.path.abspath(path)
    abs_dir = os.path.abspath(portraits_dir)
    if not abs_path.startswith(abs_dir + os.sep):
        abort(400)

    file.save(path)

    # ---- DB rows ---------------------------------------------------------
    tag = None
    if tag_name:
        tag, _ = Tag.get_or_create(tag_name)

    is_default = bool(form.is_default.data)
    is_visible = bool(form.is_visible.data)

    # Credit fields — admin can supply both, either, or neither. Default
    # the site label to "Manual upload" so the UI always has a string
    # to display in the source line.
    site_label = (form.source_site.data or '').strip() or 'Manual upload'
    src_url = (form.source_url.data or '').strip()

    portrait = Portrait(
        name=character.name,
        character_id=character.id,
        image_url=src_url,      # used as the "originating URL"; safe to be empty
        filename=filename,
        description='',
        source_url=src_url,
        source_site=site_label,
        is_default=False,       # set below if requested
        is_hidden=not is_visible,
    )

    if is_default:
        # Clear is_default on any other portraits for this character; the
        # partial unique index would otherwise reject our insert.
        Portrait.query.filter(
            Portrait.character_id == character.id,
        ).update({'is_default': False})
        portrait.is_default = True
        portrait.is_hidden = False   # defaults are always public

    db.session.add(portrait)
    db.session.flush()   # populate portrait.id (and tag.id if newly added)

    if tag is not None:
        db.session.add(TagAssociation(
            tag_id=tag.id,
            target_type='portrait',
            target_id=portrait.id,
        ))

    db.session.commit()
    flash(f"Uploaded {filename} ({size:,} bytes) for {character.name}.")
    return redirect(url_for('main.edit_character', id=character.id))


# Owner-type → (model class, edit view endpoint name) for the generic
# URL add route below. Restricting the param via this map prevents an
# attacker from inserting a Url against an arbitrary target_type value.
_URL_OWNER_TYPES = {
    'character': (Character, 'main.edit_character'),
    'event':     (Event,     'main.edit_event'),
    'location':  (Location,  'main.edit_location'),
    'faction':   (Faction,   'main.edit_faction'),
    'role':      (Role,      'main.edit_role'),
}


@main.route('/<owner_type>/<int:id>/urls/add', methods=['POST'])
@login_required
@admin_required
def add_owner_url(owner_type, id):
    """Attach a new external link (Url) to a first-class object.
    `owner_type` is one of the allow-listed keys in _URL_OWNER_TYPES;
    `id` resolves to a row in the corresponding model. After insert we
    best-effort auto-fetch a favicon from the URL's host and stash it
    under app/static/favicons/<host>_favicon.ico (deduped per host)."""
    from tools.favicon_fetcher import fetch_favicon

    if owner_type not in _URL_OWNER_TYPES:
        abort(404)
    model_cls, edit_endpoint = _URL_OWNER_TYPES[owner_type]
    owner = model_cls.query.get_or_404(id)

    form = AddUrlForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}")
        return redirect(url_for(edit_endpoint, id=owner.id))

    favicon_path = (form.favicon.data or '').strip()
    if not favicon_path:
        # Admin didn't supply one — try to fetch & cache.
        favicon_path = fetch_favicon(
            form.url.data.strip(),
            current_app.static_folder,
        ) or ''

    url = Url(
        name=form.name.data.strip(),
        url=form.url.data.strip(),
        favicon=favicon_path,
        url_type=form.url_type.data or None,
        target_type=owner_type,
        target_id=owner.id,
    )
    db.session.add(url)
    db.session.commit()
    flash(f"Added link {url.name!r} to {owner.name}.")
    return redirect(url_for(edit_endpoint, id=owner.id))


@main.route('/urls/<int:url_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_url(url_id):
    """Hard-delete a Url row. Redirects back to wherever the click came
    from (request.referrer) so the admin stays on the page they were on."""
    from flask_wtf import FlaskForm
    form = FlaskForm()
    if not form.validate_on_submit():
        abort(400)

    url = Url.query.get_or_404(url_id)
    label = url.name
    db.session.delete(url)
    db.session.commit()
    flash(f"Deleted link {label!r}.")
    return redirect(request.referrer or url_for('main.index'))


@main.route('/factions', methods=['GET'])
def factions():
    # Skip hidden factions (merged-away). To unhide, flip is_hidden=false in
    # the DB directly — no UI for it per the design.
    factions = (
        Faction.query
        .filter(Faction.is_hidden.is_(False))
        .order_by(Faction.name)
        .all()
    )

    return render_template(
        'factions/factions.html',
        factions=factions
    )

@main.route('/factions/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_faction():
    """Admin form to create a Faction. Mirrors new_character / new_event /
    new_location — same template as edit_faction with `faction=None`."""
    from sqlalchemy.exc import IntegrityError
    form = EditFactionForm()
    if form.validate_on_submit():
        faction = Faction()
        form.populate_obj(faction)
        db.session.add(faction)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A faction named {form.name.data!r} already exists.")
            return render_template('factions/faction_edit.html', form=form, faction=None)
        flash(f"Created faction {faction.name!r}.")
        return redirect(url_for('main.edit_faction', id=faction.id))
    return render_template('factions/faction_edit.html', form=form, faction=None)


@main.route('/factions/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_faction(id):
    from flask_wtf import FlaskForm
    faction = Faction.query.get_or_404(id)
    form = EditFactionForm(obj=faction)

    if form.validate_on_submit():
        form.populate_obj(faction)

        db.session.add(faction)
        db.session.commit()
        flash('The faction has been updated.')
        return redirect(url_for("main.factions"))

    # Merge form + its target picker datalist. Excludes the source itself
    # and anything already hidden.
    merge_form = MergeFactionForm()
    mergeable_factions = (
        Faction.query
        .filter(Faction.is_hidden.is_(False), Faction.id != faction.id)
        .order_by(Faction.name)
        .all()
    )

    return render_template(
        'factions/faction_edit.html',
        form=form,
        faction=faction,
        merge_form=merge_form,
        mergeable_factions=mergeable_factions,
        urls=[u for u in faction.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
    )


@main.route('/factions/<int:id>/merge', methods=['POST'])
@login_required
@admin_required
def merge_faction(id):
    """Merge faction `id` (source) into the target picked in the form.

    1. Every character with `source` in their M2M factions list ALSO gets
       `target` added (M2M is non-destructive — source link stays, but
       source is about to be hidden anyway so it falls out of all
       listings).
    2. Every character whose primary_faction is `source` gets switched
       to `target`. Other characters' primaries are not touched.
    3. `source.is_hidden` flips to True so it disappears from listings.

    The action isn't undoable from the UI — flip is_hidden back in the DB
    if you need to recover (the M2M membership added to characters stays
    either way)."""
    merge_form = MergeFactionForm()
    if not merge_form.validate_on_submit():
        abort(400)

    source = Faction.query.get_or_404(id)

    raw = (request.form.get('target_faction_id') or '').strip()
    if not raw.isdigit():
        flash("Pick a faction from the dropdown to merge into.")
        return redirect(url_for('main.edit_faction', id=id))
    target = Faction.query.get(int(raw))
    if target is None or target.is_hidden:
        flash("Target faction is missing or already hidden.")
        return redirect(url_for('main.edit_faction', id=id))
    if target.id == source.id:
        flash("Can't merge a faction into itself.")
        return redirect(url_for('main.edit_faction', id=id))

    members_carried = 0
    for character in list(source.characters):
        if target not in character.factions.all():
            character.factions.append(target)
        members_carried += 1

    primary_switched = (
        Character.query
        .filter(Character.primary_faction_id == source.id)
        .update(
            {'primary_faction_id': target.id},
            synchronize_session='fetch',
        )
    )

    source.is_hidden = True
    db.session.commit()

    flash(
        f"Merged {source.name!r} into {target.name!r}. "
        f"{members_carried} member(s) inherited the target, "
        f"{primary_switched} primary(s) switched. "
        f"{source.name!r} is now hidden."
    )
    return redirect(url_for('main.factions'))

@main.route('/roles', methods=['GET'])
def roles():

    roles = Role.query.order_by(Role.name).all()

    return render_template(
        'roles/roles.html',
        roles=roles
    )

@main.route('/roles/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_role():
    """Admin form to create a Role. Mirrors new_faction — same template
    as edit_role with `role=None`."""
    from sqlalchemy.exc import IntegrityError
    form = EditRoleForm()
    if form.validate_on_submit():
        role = Role()
        form.populate_obj(role)
        db.session.add(role)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A role named {form.name.data!r} already exists.")
            return render_template('roles/role_edit.html', form=form, role=None)
        flash(f"Created role {role.name!r}.")
        return redirect(url_for('main.edit_role', id=role.id))
    return render_template('roles/role_edit.html', form=form, role=None)


@main.route('/roles/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_role(id):
    from flask_wtf import FlaskForm
    role = Role.query.get_or_404(id)
    form = EditRoleForm(obj=role)

    if form.validate_on_submit():
        form.populate_obj(role)

        db.session.add(role)
        db.session.commit()
        flash('The role has been updated.')
        return redirect(url_for("main.roles"))

    return render_template(
        'roles/role_edit.html',
        form=form,
        role=role,
        urls=[u for u in role.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
    )


# ----- Locations ----------------------------------------------------------

@main.route('/locations', methods=['GET'])
def locations():
    page = request.args.get('page', 1, type=int)
    q = (request.args.get('q') or '').strip()
    query = Location.query.filter(Location.is_deleted.is_(False))
    if q:
        query = query.filter(Location.name.ilike(f"%{q}%"))
    pagination = query.order_by(Location.name).paginate(
        page=page,
        per_page=current_app.config['CHARACTERS_PER_PAGE'],
        error_out=False,
    )
    return render_template(
        'locations/locations.html',
        pagination=pagination,
        q=q,
        page=page,
    )


@main.route('/locations/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_location():
    form = EditLocationForm()
    if form.validate_on_submit():
        location = Location()
        form.populate_obj(location)
        location.aliases = _normalize_csv(location.aliases)
        db.session.add(location)
        db.session.commit()
        flash(f"Created location {location.name!r}.")
        return redirect(url_for('main.edit_location', id=location.id))
    return render_template('locations/location_edit.html', form=form, location=None)


@main.route('/locations/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_location(id):
    from flask_wtf import FlaskForm
    location = Location.query.get_or_404(id)
    form = EditLocationForm(obj=location)
    if form.validate_on_submit():
        form.populate_obj(location)
        location.aliases = _normalize_csv(location.aliases)
        db.session.add(location)
        db.session.commit()
        flash("Location updated.")
        return redirect(url_for('main.edit_location', id=location.id))
    return render_template(
        'locations/location_edit.html',
        form=form,
        location=location,
        urls=[u for u in location.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
    )


# ----- Events -------------------------------------------------------------

@main.route('/events', methods=['GET'])
def events():
    page = request.args.get('page', 1, type=int)
    q = (request.args.get('q') or '').strip()
    location_id = request.args.get('location_id', type=int)

    query = (
        Event.query
        .options(selectinload(Event.chapters))
        .filter(Event.is_deleted.is_(False))
    )
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Event.name.ilike(like)) | (Event.aliases.ilike(like))
        )
    if location_id:
        query = query.filter(Event.location_id == location_id)

    pagination = query.order_by(Event.name).paginate(
        page=page,
        per_page=current_app.config['CHARACTERS_PER_PAGE'],
        error_out=False,
    )

    locations_for_filter = Location.query.filter(Location.is_deleted.is_(False))\
                                         .order_by(Location.name).all()

    # Sorted-by-chapter-num chapter list per event, for the table column.
    chapter_lists = {
        e.id: sorted(e.chapters, key=lambda c: c.chapter_num)
        for e in pagination.items
    }

    return render_template(
        'events/events.html',
        pagination=pagination,
        q=q,
        location_id=location_id,
        locations=locations_for_filter,
        chapter_lists=chapter_lists,
        page=page,
    )


@main.route('/events/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_event():
    form = EditEventForm()
    if form.validate_on_submit():
        event = Event()
        form.populate_obj(event)
        event.aliases = _normalize_csv(event.aliases)
        db.session.add(event)
        db.session.commit()
        flash(f"Created event {event.name!r}.")
        return redirect(url_for('main.edit_event', id=event.id))
    return render_template('events/event_edit.html', form=form, event=None)


@main.route('/events/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_event(id):
    from flask_wtf import FlaskForm
    event = Event.query.get_or_404(id)
    form = EditEventForm(obj=event)
    if form.validate_on_submit():
        form.populate_obj(event)
        event.aliases = _normalize_csv(event.aliases)
        db.session.add(event)
        db.session.commit()
        flash("Event updated.")
        return redirect(url_for('main.edit_event', id=event.id))
    return render_template(
        'events/event_edit.html',
        form=form,
        event=event,
        urls=[u for u in event.urls if not u.is_deleted],
        add_url_form=AddUrlForm(),
        csrf_form=FlaskForm(),
    )
