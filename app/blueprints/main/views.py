import os
import re
import string
from flask import render_template, abort, request, current_app, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from app import db
from app.models import Chapter, Character, Faction, Role, Tag, TagAssociation
from app.models.character import Portrait, PORTRAIT_DIR
from . import main
from .forms import EditCharacterForm, EditFactionForm, EditRoleForm, \
    CharacterFilterForm, UploadPortraitForm, MergeFactionForm

from tools.decorators import admin_required
from tools.book_parser import get_characters_for_chapter, build_needle_pattern, build_name_ref_html, count_mentions_per_character


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

    for character in characters:
        for name_needle in character.get_all_name_labels():
            replacements[name_needle] = build_name_ref_html(character)
            needle_to_character_id[name_needle] = character.id

    pattern = build_needle_pattern(list(replacements.keys()))

    # Count mentions per character as a side-effect of the rendering pass —
    # avoids a second scan of the chapter content for the sidebar's
    # "N mentions" badges.
    mention_counts = defaultdict(int)

    def replace_match(match):
        matched = match.group(0)
        cid = needle_to_character_id.get(matched)
        if cid is not None:
            mention_counts[cid] += 1
        return replacements[matched]

    rendered_content = pattern.sub(replace_match, chapter.content) if replacements else chapter.content

    return render_template(
        'book/chapter.html',
        chapter=chapter,
        chapter_content=rendered_content,
        characters=characters,
        mention_counts=mention_counts,
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

    portrait = Portrait(
        name=character.name,
        character_id=character.id,
        image_url='',           # no remote URL for manual uploads
        filename=filename,
        description='',
        source_url='',
        source_site='Manual upload',
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

@main.route('/factions/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_faction(id):
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

@main.route('/roles/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_role(id):
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
        form=form
    )
