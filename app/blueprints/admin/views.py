import os
import re

from flask import render_template, redirect, url_for, flash, current_app, abort, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import SubmitField

from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import db
from app.models import User, Chapter, Character, Faction, Role, Tag, TagAssociation, Url, UrlType, Event, Edit
from app.models.character import Portrait, PORTRAIT_DIR
from tools.decorators import admin_required
from tools.book_parser import find_character_mentions, find_event_mentions, count_mentions_per_character, strip_html_tags, build_needle_pattern
from .forms import EditTagForm, CreateUserForm, EditUrlTypeForm
from . import admin


PORTRAIT_TARGET_TYPE = 'portrait'   # TagAssociation.target_type for Portrait rows.


@admin.route('/faq', methods=['GET'])
@login_required
@admin_required
def faq():
    """How-to reference for the most common admin tasks. Static content
    — lives in templates/admin/faq.html — but admin-gated so it isn't
    indexed and link references can assume the reader has admin rights."""
    return render_template('admin/faq.html')


def _factions_by_character_id(character_ids):
    """Return {character_id: [faction_name, ...]} for the given character ids."""
    return _m2m_names_by_character_id(
        character_ids,
        Character.faction_table,
        Faction,
        Character.faction_table.c.faction_id,
    )


def _roles_by_character_id(character_ids):
    """Return {character_id: [role_name, ...]} for the given character ids."""
    return _m2m_names_by_character_id(
        character_ids,
        Character.role_table,
        Role,
        Character.role_table.c.role_id,
    )


def _m2m_names_by_character_id(character_ids, assoc_table, target_model, target_fk_col):
    """Shared driver for the two _*_by_character_id helpers.

    Character.factions and Character.roles are both lazy='dynamic', which
    blocks selectinload, so we go straight at the M2M association table
    with one explicit join. Hidden Factions / Roles are filtered out so
    merged-away tags don't keep appearing in the picker annotations.
    Empty input -> empty dict."""
    if not character_ids:
        return {}
    rows = (
        db.session.query(
            assoc_table.c.character_id,
            target_model.name,
        )
        .join(target_model, target_model.id == target_fk_col)
        .filter(
            assoc_table.c.character_id.in_(character_ids),
            target_model.is_hidden.is_(False),
        )
        .order_by(target_model.name)
        .all()
    )
    out = {}
    for cid, name in rows:
        out.setdefault(cid, []).append(name)
    return out


class _CsrfOnlyForm(FlaskForm):
    """Empty form used to CSRF-protect POST buttons (toggle-admin)."""
    submit = SubmitField()


@admin.route('/users', methods=['GET'])
@login_required
@admin_required
def users():
    page = current_app.config.get('USERS_PER_PAGE', 50)
    pagination = User.query.order_by(User.username).paginate(
        page=1,
        per_page=page,
        error_out=False,
    )
    return render_template(
        'admin/users.html',
        users=pagination.items,
        pagination=pagination,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_user():
    """Admin-only form to create a new user, optionally with admin access.

    The user is marked confirmed (no email verification needed — the
    admin is vouching), and is_administrator follows the checkbox.
    Duplicate email / username are caught by CreateUserForm validators
    before we hit the DB, so the only failure path here would be a race
    with another insert — IntegrityError fallback for safety."""
    form = CreateUserForm()
    if form.validate_on_submit():
        user = User(
            email=form.email.data.lower(),
            username=form.username.data,
            confirmed=True,
            is_administrator=bool(form.is_administrator.data),
        )
        user.password = form.password.data
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Couldn't create the user — email or username may "
                  "have just been taken by another insert.")
            return render_template('admin/user_new.html', form=form)

        suffix = " (admin)" if user.is_administrator else ""
        flash(f"Created user {user.username}{suffix}.")
        return redirect(url_for('admin.users'))

    return render_template('admin/user_new.html', form=form)


@admin.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    target = User.query.get_or_404(user_id)

    if target.id == current_user.id:
        flash("You can't change your own admin status. Ask another admin.")
        return redirect(url_for('admin.users'))

    if target.is_administrator:
        remaining_admins = User.query.filter(
            User.is_administrator.is_(True),
            User.id != target.id,
        ).count()
        if remaining_admins == 0:
            flash("Can't remove the last administrator.")
            return redirect(url_for('admin.users'))
        target.is_administrator = False
        flash(f"Removed admin from {target.username}.")
    else:
        if not target.confirmed:
            flash(f"Can't promote {target.username} until they've confirmed their email.")
            return redirect(url_for('admin.users'))
        target.is_administrator = True
        flash(f"Promoted {target.username} to admin.")

    db.session.add(target)
    db.session.commit()
    return redirect(url_for('admin.users'))


# ----- Chapter ↔ Character association editor -----------------------------

@admin.route('/chapter-associations', methods=['GET'])
@admin.route('/chapter-associations/<int:chapter_num>', methods=['GET'])
@login_required
@admin_required
def chapter_associations(chapter_num=None):
    # The chapter picker is a plain GET form, so it submits as ?chapter_num=N.
    # Redirect to the cleaner path-style URL so the page is shareable and the
    # URL reflects the selection.
    if chapter_num is None:
        from_query = request.args.get('chapter_num', type=int)
        if from_query is not None:
            return redirect(url_for('admin.chapter_associations', chapter_num=from_query))

    chapters = Chapter.query.order_by(Chapter.chapter_num).all()

    selected = None
    rows = []
    faction_options = []
    all_characters = []

    if chapter_num is not None:
        selected = Chapter.query.filter_by(chapter_num=chapter_num).first()
        if selected is None:
            abort(404)

        associated = sorted(selected.characters, key=lambda c: c.name)
        seen_factions = {}
        for character in associated:
            mentions = find_character_mentions(selected, character, limit=10)
            rows.append({
                'character': character,
                'mentions': mentions,
                'mention_count': len(mentions),
                'roles': list(character.roles),
                'faction': character.primary_faction,
            })
            if character.primary_faction is not None:
                seen_factions[character.primary_faction.id] = character.primary_faction
        faction_options = sorted(seen_factions.values(), key=lambda f: f.name)

        # Both the per-row Switch picker and the Add Character Association
        # form below need to pick from every character (the Add form might
        # want to attach an alias to a character that's already in the
        # chapter; the Switch form might pick one not currently here).
        all_characters = Character.query.order_by(Character.name).all()

    # Names that appear on more than one character — kept around so the
    # picker can still annotate ambiguous-name cases distinctly if we want.
    from collections import Counter
    name_counter = Counter(c.name for c in all_characters)
    duplicate_names = {name for name, n in name_counter.items() if n > 1}
    char_ids = [c.id for c in all_characters]
    factions_by_char = _factions_by_character_id(char_ids)
    roles_by_char = _roles_by_character_id(char_ids)

    return render_template(
        'admin/chapter_associations.html',
        chapters=chapters,
        selected=selected,
        rows=rows,
        faction_options=faction_options,
        all_characters=all_characters,
        duplicate_names=duplicate_names,
        factions_by_char=factions_by_char,
        roles_by_char=roles_by_char,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/chapter-associations/<int:chapter_num>/remove/<int:character_id>', methods=['POST'])
@login_required
@admin_required
def chapter_associations_remove(chapter_num, character_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    character = Character.query.get_or_404(character_id)

    if character in chapter.characters:
        chapter.characters.remove(character)
        db.session.commit()
        flash(f"Removed {character.name} from chapter {chapter.chapter_num}.")
    else:
        flash(f"{character.name} is not associated with chapter {chapter.chapter_num}.")

    return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))


_ID_SUFFIX_RE = re.compile(r'\s*#(\d+)\s*$')


def _resolve_character_from_form():
    """Pull (character_id, character_name) out of request.form and resolve to
    a single Character or (None, error_message_to_flash). Used by both the
    add and switch flows — they share the same picker pattern.

    Resolution order:
      1. Explicit `character_id` field (set by the JS picker).
      2. `Name #<id>` suffix in `character_name` — fallback when JS hasn't
         populated the hidden field but the user picked from the datalist
         (the option values always carry the suffix for disambiguation).
      3. Plain `character_name` exact match (errors on duplicates).
    """
    raw_id = (request.form.get('character_id') or '').strip()
    raw_name = (request.form.get('character_name') or '').strip()

    if raw_id.isdigit():
        character = Character.query.get(int(raw_id))
        if character is None:
            return None, "Couldn't find a character with that id."
        return character, None

    if raw_name:
        m = _ID_SUFFIX_RE.search(raw_name)
        if m:
            character = Character.query.get(int(m.group(1)))
            if character is None:
                return None, "Couldn't find a character with that id."
            return character, None

        matches = Character.query.filter(Character.name == raw_name).all()
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, (
                f"Multiple characters named {raw_name!r}. Pick one from the "
                f"dropdown (each option has a unique '#<id>' suffix) instead "
                f"of typing the bare name."
            )
    return None, "Couldn't find a character matching that selection."


@admin.route('/chapter-associations/<int:chapter_num>/add', methods=['POST'])
@login_required
@admin_required
def chapter_associations_add(chapter_num):
    """Add a Character ↔ Chapter association by alias.

    Admin provides a `search_term` (the name as it appears in the chapter
    text) and picks the canonical character. We verify the term occurs in
    the chapter, add it to the character's aliases (so the rendered chapter
    tags those occurrences), and associate the character with the chapter."""
    from tools.book_parser import strip_html_tags, build_needle_pattern

    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()

    search_term = (request.form.get('search_term') or '').strip()
    if not search_term:
        flash("Search term is required.")
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    character, err = _resolve_character_from_form()
    if err:
        flash(err)
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    content = strip_html_tags(chapter.content)
    matches = build_needle_pattern([search_term]).findall(content)
    if not matches:
        flash(f"{search_term!r} was not found in chapter {chapter.chapter_num}'s text.")
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    # Add the search term to character.aliases if it isn't already a known
    # label for this character (covers name, courtesy name, alias).
    existing = [a.strip() for a in (character.aliases or '').split(',') if a.strip()]
    known_labels = {character.name, character.courtesty_name or ''}
    known_labels.update(existing)
    alias_added = False
    if search_term not in known_labels:
        existing.append(search_term)
        character.aliases = ','.join(existing)
        alias_added = True

    if character not in chapter.characters:
        chapter.characters.append(character)

    # The character's labels just changed → its book_mention_count is stale.
    # Recount this one character (cheap: one HTML-strip pass, one regex).
    if alias_added:
        counts = count_mentions_per_character(Chapter.query.all(), [character])
        character.book_mention_count = counts.get(character.id, 0)

    db.session.commit()

    parts = [f"Found {len(matches)} occurrence{'' if len(matches) == 1 else 's'} of {search_term!r}."]
    if alias_added:
        parts.append(f"Added {search_term!r} as an alias of {character.name}.")
    parts.append(f"{character.name} is now associated with chapter {chapter.chapter_num}.")
    flash(" ".join(parts))

    return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))


@admin.route('/chapter-associations/<int:chapter_num>/switch/<int:character_id>', methods=['POST'])
@login_required
@admin_required
def chapter_associations_switch(chapter_num, character_id):
    """Swap which character a chapter association points at.

    Keeps the chapter the same; removes the old character and adds the new
    one. Used when the scanner picked the wrong character for a name."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    old_character = Character.query.get_or_404(character_id)

    new_character, err = _resolve_character_from_form()
    if err:
        flash(err)
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    if new_character.id == old_character.id:
        flash(f"{new_character.name} is already the associated character — nothing to switch.")
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    if old_character in chapter.characters:
        chapter.characters.remove(old_character)
    if new_character not in chapter.characters:
        chapter.characters.append(new_character)
    db.session.commit()

    flash(
        f"Switched {old_character.name} → {new_character.name} in "
        f"chapter {chapter.chapter_num}."
    )
    return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))


# ----- Chapter ↔ Event association editor ---------------------------------

def _resolve_event_from_form():
    """Same shape as _resolve_character_from_form but for Events. Reads
    `event_id` (preferred) or `event_name` ("Name #id" or bare name)
    out of request.form. Returns (event, error_message_to_flash)."""
    raw_id = (request.form.get('event_id') or '').strip()
    raw_name = (request.form.get('event_name') or '').strip()

    if raw_id.isdigit():
        event = Event.query.get(int(raw_id))
        if event is None:
            return None, "Couldn't find an event with that id."
        return event, None

    if raw_name:
        m = _ID_SUFFIX_RE.search(raw_name)
        if m:
            event = Event.query.get(int(m.group(1)))
            if event is None:
                return None, "Couldn't find an event with that id."
            return event, None
        matches = Event.query.filter(Event.name == raw_name).all()
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, (
                f"Multiple events named {raw_name!r}. Pick from the dropdown "
                f"(each option carries a unique '#<id>' suffix)."
            )
    return None, "Couldn't find an event matching that selection."


@admin.route('/event-associations', methods=['GET'])
@admin.route('/event-associations/<int:chapter_num>', methods=['GET'])
@login_required
@admin_required
def event_associations(chapter_num=None):
    """Mirror of chapter_associations but for Events. Pick a chapter,
    see the events associated with it, add new associations by keyword
    list (comma-separated), switch a wrong association, or remove one."""
    if chapter_num is None:
        from_query = request.args.get('chapter_num', type=int)
        if from_query is not None:
            return redirect(url_for('admin.event_associations', chapter_num=from_query))

    chapters = Chapter.query.order_by(Chapter.chapter_num).all()
    selected = None
    rows = []
    all_events = []

    if chapter_num is not None:
        selected = Chapter.query.filter_by(chapter_num=chapter_num).first()
        if selected is None:
            abort(404)

        associated = sorted(selected.events, key=lambda e: e.name)
        for event in associated:
            mentions = find_event_mentions(selected, event, limit=10)
            rows.append({
                'event': event,
                'mentions': mentions,
                'mention_count': len(mentions),
                'location': event.location,
            })

        all_events = (
            Event.query
            .filter(Event.is_deleted.is_(False))
            .order_by(Event.name)
            .all()
        )

    return render_template(
        'admin/event_associations.html',
        chapters=chapters,
        selected=selected,
        rows=rows,
        all_events=all_events,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/event-associations/<int:chapter_num>/add', methods=['POST'])
@login_required
@admin_required
def event_associations_add(chapter_num):
    """Attach an Event to a chapter, adding keyword aliases as we go.

    Admin supplies a comma-separated `search_terms` field. For each
    keyword we verify it appears in the chapter text (HTML stripped)
    and, if so, append it to event.aliases (deduped against name +
    existing aliases). Keywords that don't appear in the chapter are
    reported back but otherwise skipped. The chapter ↔ event link is
    added regardless (admin opted to associate)."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()

    event, err = _resolve_event_from_form()
    if err:
        flash(err)
        return redirect(url_for('admin.event_associations', chapter_num=chapter_num))

    raw_terms = (request.form.get('search_terms') or '').strip()
    keywords = [k.strip() for k in raw_terms.split(',') if k.strip()]
    if not keywords:
        flash("Enter at least one keyword (comma-separated for multiple).")
        return redirect(url_for('admin.event_associations', chapter_num=chapter_num))

    content = strip_html_tags(chapter.content)
    existing = [a.strip() for a in (event.aliases or '').split(',') if a.strip()]
    known = {event.name} | set(existing)

    aliases_added = []
    no_match = []
    for keyword in keywords:
        if not build_needle_pattern([keyword]).findall(content):
            no_match.append(keyword)
            continue
        if keyword not in known:
            existing.append(keyword)
            known.add(keyword)
            aliases_added.append(keyword)

    if aliases_added:
        event.aliases = ','.join(existing)

    if event not in chapter.events:
        chapter.events.append(event)

    db.session.commit()

    parts = []
    if aliases_added:
        parts.append("Added aliases: " + ", ".join(repr(a) for a in aliases_added) + ".")
    if no_match:
        parts.append("Skipped (not found in chapter): " + ", ".join(repr(k) for k in no_match) + ".")
    parts.append(f"{event.name!r} is now associated with chapter {chapter.chapter_num}.")
    flash(" ".join(parts))

    return redirect(url_for('admin.event_associations', chapter_num=chapter_num))


@admin.route('/event-associations/<int:chapter_num>/remove/<int:event_id>', methods=['POST'])
@login_required
@admin_required
def event_associations_remove(chapter_num, event_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    event = Event.query.get_or_404(event_id)

    if event in chapter.events:
        chapter.events.remove(event)
        db.session.commit()
        flash(f"Removed {event.name!r} from chapter {chapter.chapter_num}.")
    else:
        flash(f"{event.name!r} was not associated with chapter {chapter.chapter_num}.")
    return redirect(url_for('admin.event_associations', chapter_num=chapter_num))


@admin.route('/event-associations/<int:chapter_num>/switch/<int:event_id>', methods=['POST'])
@login_required
@admin_required
def event_associations_switch(chapter_num, event_id):
    """Swap which event a chapter association points at — keep chapter,
    remove old, add new."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    old_event = Event.query.get_or_404(event_id)

    new_event, err = _resolve_event_from_form()
    if err:
        flash(err)
        return redirect(url_for('admin.event_associations', chapter_num=chapter_num))

    if new_event.id == old_event.id:
        flash(f"{new_event.name!r} is already the associated event.")
        return redirect(url_for('admin.event_associations', chapter_num=chapter_num))

    if old_event in chapter.events:
        chapter.events.remove(old_event)
    if new_event not in chapter.events:
        chapter.events.append(new_event)
    db.session.commit()

    flash(f"Switched {old_event.name!r} → {new_event.name!r} in chapter {chapter.chapter_num}.")
    return redirect(url_for('admin.event_associations', chapter_num=chapter_num))


# ----- Image Manager -------------------------------------------------------

# Each row is one Portrait (a character with N images shows up N times).
_PORTRAIT_SORTS = ('character', 'source_site', 'created_at')
_PORTRAITS_PER_PAGE = 25


@admin.route('/images', methods=['GET'])
@login_required
@admin_required
def image_manager():
    page = request.args.get('page', 1, type=int)
    search = (request.args.get('q') or '').strip()
    source_site = (request.args.get('source_site') or '').strip()
    tag_id = request.args.get('tag_id', type=int)
    character_id = request.args.get('character_id', type=int)
    sort = request.args.get('sort', 'character')
    direction = request.args.get('dir', 'asc')

    if sort not in _PORTRAIT_SORTS:
        sort = 'character'
    if direction not in ('asc', 'desc'):
        direction = 'asc'

    query = (
        Portrait.query
        .join(Character, Character.id == Portrait.character_id)
        .filter(Portrait.is_deleted.is_(False))
        # Batch-load tags for each portrait row so the template doesn't N+1.
        .options(selectinload(Portrait.tags))
    )

    # Character filter: prefer the explicit id (set by the JS picker, or
    # parsed out of the trailing "#<id>" in `q` if JS didn't fire). Fall
    # back to substring search on name + description for free-form text.
    if character_id is None and search:
        m = re.search(r'#(\d+)\s*$', search)
        if m:
            character_id = int(m.group(1))

    if character_id:
        query = query.filter(Portrait.character_id == character_id)
    elif search:
        like = f"%{search}%"
        query = query.filter(or_(
            Character.name.ilike(like),
            Portrait.description.ilike(like),
        ))

    if source_site:
        query = query.filter(Portrait.source_site == source_site)

    if tag_id:
        # Inner-join the polymorphic association limited to this tag so we
        # only get portraits that actually have it attached.
        query = query.join(
            TagAssociation,
            (TagAssociation.target_type == PORTRAIT_TARGET_TYPE)
            & (TagAssociation.target_id == Portrait.id)
            & (TagAssociation.tag_id == tag_id),
        )

    if sort == 'character':
        order_col = Character.name
    elif sort == 'source_site':
        order_col = Portrait.source_site
    else:  # 'created_at'
        order_col = Portrait.created_at
    query = query.order_by(order_col.desc() if direction == 'desc' else order_col.asc())
    # Deterministic tiebreak so the same row order ships across pages.
    query = query.order_by(Portrait.id.asc())

    pagination = query.paginate(
        page=page,
        per_page=_PORTRAITS_PER_PAGE,
        error_out=False,
    )

    source_sites = [
        row[0] for row in (
            db.session.query(Portrait.source_site)
            .filter(Portrait.is_deleted.is_(False), Portrait.source_site != '')
            .distinct()
            .order_by(Portrait.source_site)
            .all()
        )
    ]

    all_tags = Tag.query.order_by(Tag.name).all()

    # Picker data for the character search box — same shape as chapter
    # associations: every character is a datalist option whose value is
    # "<name> #<id>" so duplicate names disambiguate, plus a label that
    # tacks the factions on for duplicate-name characters.
    all_characters = Character.query.order_by(Character.name).all()
    from collections import Counter
    name_counter = Counter(c.name for c in all_characters)
    duplicate_names = {n for n, count in name_counter.items() if count > 1}
    char_ids = [c.id for c in all_characters]
    factions_by_char = _factions_by_character_id(char_ids)
    roles_by_char = _roles_by_character_id(char_ids)

    return render_template(
        'admin/image_manager.html',
        pagination=pagination,
        source_sites=source_sites,
        all_tags=all_tags,
        all_characters=all_characters,
        duplicate_names=duplicate_names,
        factions_by_char=factions_by_char,
        roles_by_char=roles_by_char,
        search=search,
        source_site=source_site,
        tag_id=tag_id,
        character_id=character_id,
        sort=sort,
        direction=direction,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/images/<int:portrait_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_portrait(portrait_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    portrait = Portrait.query.get_or_404(portrait_id)
    character_name = portrait.character.name if portrait.character else '(unknown)'

    # Remove the file on disk too, so a re-scrape with --refresh starts clean.
    # `filename` is set by us as a basename — defensively reject anything that
    # tries to escape PORTRAIT_DIR.
    if portrait.filename and '/' not in portrait.filename and '\\' not in portrait.filename:
        path = os.path.join(current_app.static_folder, PORTRAIT_DIR, portrait.filename)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    db.session.delete(portrait)
    db.session.commit()
    flash(f"Deleted portrait for {character_name}.")
    return redirect(request.referrer or url_for('admin.image_manager'))


@admin.route('/images/<int:portrait_id>/tags/add', methods=['POST'])
@login_required
@admin_required
def add_portrait_tag(portrait_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    portrait = Portrait.query.get_or_404(portrait_id)
    tag_id = request.form.get('tag_id', type=int)
    if not tag_id:
        flash("No tag selected.")
        return redirect(request.referrer or url_for('admin.image_manager'))

    tag = Tag.query.get_or_404(tag_id)
    assoc = TagAssociation(
        tag_id=tag.id,
        target_type=PORTRAIT_TARGET_TYPE,
        target_id=portrait.id,
    )
    db.session.add(assoc)
    try:
        db.session.commit()
        flash(f"Added tag {tag.name!r} to portrait.")
    except IntegrityError:
        # UniqueConstraint(tag_id, target_type, target_id) — already attached.
        db.session.rollback()
        flash(f"Tag {tag.name!r} is already attached to this portrait.")

    return redirect(request.referrer or url_for('admin.image_manager'))


@admin.route('/images/<int:portrait_id>/toggle-hidden', methods=['POST'])
@login_required
@admin_required
def toggle_portrait_hidden(portrait_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    portrait = Portrait.query.get_or_404(portrait_id)
    portrait.is_hidden = not portrait.is_hidden
    # A hidden Portrait can't simultaneously be the default — clear it.
    if portrait.is_hidden and portrait.is_default:
        portrait.is_default = False
    db.session.commit()
    return redirect(request.referrer or url_for('admin.image_manager'))


@admin.route('/images/<int:portrait_id>/set-default', methods=['POST'])
@login_required
@admin_required
def set_default_portrait(portrait_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    portrait = Portrait.query.get_or_404(portrait_id)

    # Clear is_default on any other portraits for this character first.
    # Their is_hidden state is intentionally not touched — only the chosen
    # default is affected by this route.
    Portrait.query.filter(
        Portrait.character_id == portrait.character_id,
        Portrait.id != portrait.id,
    ).update({'is_default': False})

    portrait.is_default = True
    # Defaults are always public — auto-unhide if it was hidden.
    portrait.is_hidden = False
    db.session.commit()
    return redirect(request.referrer or url_for('admin.image_manager'))


@admin.route('/images/<int:portrait_id>/tags/<int:tag_id>/remove', methods=['POST'])
@login_required
@admin_required
def remove_portrait_tag(portrait_id, tag_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    assoc = TagAssociation.query.filter_by(
        target_type=PORTRAIT_TARGET_TYPE,
        target_id=portrait_id,
        tag_id=tag_id,
    ).first()
    if assoc is not None:
        db.session.delete(assoc)
        db.session.commit()

    return redirect(request.referrer or url_for('admin.image_manager'))


# ----- Duplicate character names ------------------------------------------

@admin.route('/duplicates', methods=['GET'])
@login_required
@admin_required
def duplicate_characters():
    """List every Character.name that appears more than once. Name comparison
    is byte-wise (collation 'C') — 'Cao Cao' and 'cao cao' aren't flagged as
    duplicates by design. is_deleted rows are excluded."""
    rows = (
        db.session.query(
            Character.name,
            func.count(Character.id).label('count'),
        )
        .filter(Character.is_deleted.is_(False))
        .group_by(Character.name)
        .having(func.count(Character.id) > 1)
        .order_by(func.count(Character.id).desc(), Character.name)
        .all()
    )

    # For each duplicated name, pull the actual Character rows so the admin
    # can click through. One query for all of them via a name-IN filter.
    duplicate_names = [r[0] for r in rows]
    chars_by_name = {}
    if duplicate_names:
        for c in (
            Character.query
            .filter(
                Character.name.in_(duplicate_names),
                Character.is_deleted.is_(False),
            )
            .order_by(Character.name, Character.id)
            .all()
        ):
            chars_by_name.setdefault(c.name, []).append(c)

    factions_by_char = _factions_by_character_id(
        [c.id for cs in chars_by_name.values() for c in cs]
    )

    return render_template(
        'admin/duplicates.html',
        rows=rows,
        chars_by_name=chars_by_name,
        factions_by_char=factions_by_char,
    )


# ----- Edits (audit log) ---------------------------------------------------

_EDIT_SORTS = ('created_at', 'target_type', 'user_label', 'action')
_EDITS_PER_PAGE = 50


@admin.route('/edits', methods=['GET'])
@login_required
@admin_required
def edits():
    page = request.args.get('page', 1, type=int)
    search = (request.args.get('q') or '').strip()
    target_type = (request.args.get('target_type') or '').strip()
    action = (request.args.get('action') or '').strip()
    user_label = (request.args.get('user_label') or '').strip()
    sort = request.args.get('sort', 'created_at')
    direction = request.args.get('dir', 'desc')

    if sort not in _EDIT_SORTS:
        sort = 'created_at'
    if direction not in ('asc', 'desc'):
        direction = 'desc'

    query = Edit.query

    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Edit.user_label.ilike(like),
            Edit.target_type.ilike(like),
        ))

    if target_type:
        query = query.filter(Edit.target_type == target_type)

    if action:
        query = query.filter(Edit.action == action)

    if user_label:
        query = query.filter(Edit.user_label == user_label)

    order_col = getattr(Edit, sort)
    query = query.order_by(order_col.desc() if direction == 'desc' else order_col.asc())
    if sort != 'created_at':
        query = query.order_by(Edit.created_at.desc())  # deterministic tiebreak

    pagination = query.paginate(page=page, per_page=_EDITS_PER_PAGE, error_out=False)

    # Filter-dropdown options come from distinct values currently in the
    # table — cheap because of the indexes on these columns.
    target_types = [
        r[0] for r in
        db.session.query(Edit.target_type).distinct().order_by(Edit.target_type).all()
    ]
    user_labels = [
        r[0] for r in
        db.session.query(Edit.user_label).distinct().order_by(Edit.user_label).all()
        if r[0]
    ]

    return render_template(
        'admin/edits.html',
        pagination=pagination,
        target_types=target_types,
        user_labels=user_labels,
        search=search,
        target_type=target_type,
        action=action,
        user_label=user_label,
        sort=sort,
        direction=direction,
    )


# ----- Tag manager ---------------------------------------------------------

_TAG_SORTS = ('name', 'created_at', 'image_count')
_TAGS_PER_PAGE = 50


@admin.route('/tags', methods=['GET'])
@login_required
@admin_required
def tags():
    page = request.args.get('page', 1, type=int)
    search = (request.args.get('q') or '').strip()
    sort = request.args.get('sort', 'name')
    direction = request.args.get('dir', 'asc')

    if sort not in _TAG_SORTS:
        sort = 'name'
    if direction not in ('asc', 'desc'):
        direction = 'asc'

    # One subquery counts how many portraits each tag is attached to, joined
    # back to Tag with COALESCE so tags with zero associations sort as 0
    # instead of NULL.
    image_counts = (
        db.session.query(
            TagAssociation.tag_id.label('tag_id'),
            func.count(TagAssociation.id).label('image_count'),
        )
        .filter(TagAssociation.target_type == PORTRAIT_TARGET_TYPE)
        .group_by(TagAssociation.tag_id)
        .subquery()
    )
    image_count_expr = func.coalesce(image_counts.c.image_count, 0)

    query = (
        Tag.query
        .outerjoin(image_counts, Tag.id == image_counts.c.tag_id)
        .add_columns(image_count_expr.label('image_count'))
    )
    if search:
        query = query.filter(Tag.name.ilike(f"%{search}%"))

    if sort == 'image_count':
        order_col = image_count_expr
    else:
        order_col = getattr(Tag, sort)
    query = query.order_by(order_col.desc() if direction == 'desc' else order_col.asc())
    if sort != 'name':
        query = query.order_by(Tag.name.asc())  # deterministic tiebreak

    pagination = query.paginate(page=page, per_page=_TAGS_PER_PAGE, error_out=False)

    return render_template(
        'admin/tags.html',
        pagination=pagination,
        search=search,
        sort=sort,
        direction=direction,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/tags/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_tag():
    form = EditTagForm()
    if form.validate_on_submit():
        tag = Tag()
        form.populate_obj(tag)
        db.session.add(tag)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A tag named {tag.name!r} already exists.")
            return redirect(url_for('admin.new_tag'))
        flash(f"Created tag {tag.name!r}.")
        return redirect(url_for('admin.tags'))

    return render_template('admin/tag_edit.html', form=form, tag=None)


@admin.route('/tags/<int:tag_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_tag(tag_id):
    tag = Tag.query.get_or_404(tag_id)
    form = EditTagForm(obj=tag)
    if form.validate_on_submit():
        form.populate_obj(tag)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A tag named {tag.name!r} already exists.")
            return redirect(url_for('admin.edit_tag', tag_id=tag.id))
        flash(f"Updated tag {tag.name!r}.")
        return redirect(url_for('admin.tags'))

    return render_template('admin/tag_edit.html', form=form, tag=tag)


@admin.route('/tags/<int:tag_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_tag(tag_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    tag = Tag.query.get_or_404(tag_id)
    name = tag.name

    # Refuse to delete if any image is using this tag. Belt-and-braces: the
    # template hides the delete button for in-use tags, but this is the
    # authoritative check (race conditions, direct curls).
    image_uses = TagAssociation.query.filter_by(
        tag_id=tag.id,
        target_type=PORTRAIT_TARGET_TYPE,
    ).count()
    if image_uses > 0:
        flash(
            f"Can't delete {name!r}: it's attached to {image_uses} image"
            f"{'' if image_uses == 1 else 's'}. Detach it from those first."
        )
        return redirect(url_for('admin.tags'))

    db.session.delete(tag)   # cascade removes any non-image TagAssociation rows
    db.session.commit()
    flash(f"Deleted tag {name!r}.")
    return redirect(url_for('admin.tags'))


# ----- URL Type manager ----------------------------------------------------

_URL_TYPE_SORTS = ('name', 'created_at', 'url_count')
_URL_TYPES_PER_PAGE = 50


@admin.route('/url-types', methods=['GET'])
@login_required
@admin_required
def url_types():
    page = request.args.get('page', 1, type=int)
    search = (request.args.get('q') or '').strip()
    sort = request.args.get('sort', 'name')
    direction = request.args.get('dir', 'asc')

    if sort not in _URL_TYPE_SORTS:
        sort = 'name'
    if direction not in ('asc', 'desc'):
        direction = 'asc'

    # Subquery counts how many Urls use each UrlType — same pattern as the
    # tag image-count subquery on /admin/tags. Outer-joined so types with
    # zero urls show 0 rather than NULL.
    url_counts = (
        db.session.query(
            Url.url_type_id.label('url_type_id'),
            func.count(Url.id).label('url_count'),
        )
        .filter(Url.is_deleted.is_(False))
        .group_by(Url.url_type_id)
        .subquery()
    )
    url_count_expr = func.coalesce(url_counts.c.url_count, 0)

    query = (
        UrlType.query
        .outerjoin(url_counts, UrlType.id == url_counts.c.url_type_id)
        .add_columns(url_count_expr.label('url_count'))
        .filter(UrlType.is_hidden.is_(False))
    )
    if search:
        query = query.filter(UrlType.name.ilike(f"%{search}%"))

    if sort == 'url_count':
        order_col = url_count_expr
    else:
        order_col = getattr(UrlType, sort)
    query = query.order_by(order_col.desc() if direction == 'desc' else order_col.asc())
    if sort != 'name':
        query = query.order_by(UrlType.name.asc())

    pagination = query.paginate(page=page, per_page=_URL_TYPES_PER_PAGE, error_out=False)

    return render_template(
        'admin/url_types.html',
        pagination=pagination,
        search=search,
        sort=sort,
        direction=direction,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/url-types/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_url_type():
    form = EditUrlTypeForm()
    if form.validate_on_submit():
        url_type = UrlType()
        form.populate_obj(url_type)
        db.session.add(url_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A URL type named {url_type.name!r} already exists.")
            return redirect(url_for('admin.new_url_type'))
        flash(f"Created URL type {url_type.name!r}.")
        return redirect(url_for('admin.url_types'))

    return render_template('admin/url_type_edit.html', form=form, url_type=None)


@admin.route('/url-types/<int:url_type_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_url_type(url_type_id):
    url_type = UrlType.query.get_or_404(url_type_id)
    form = EditUrlTypeForm(obj=url_type)
    if form.validate_on_submit():
        form.populate_obj(url_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A URL type named {url_type.name!r} already exists.")
            return redirect(url_for('admin.edit_url_type', url_type_id=url_type.id))
        flash(f"Updated URL type {url_type.name!r}.")
        return redirect(url_for('admin.url_types'))

    return render_template('admin/url_type_edit.html', form=form, url_type=url_type)


@admin.route('/url-types/<int:url_type_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_url_type(url_type_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    url_type = UrlType.query.get_or_404(url_type_id)
    name = url_type.name

    # Refuse if any Url is currently using it. ON DELETE SET NULL on the FK
    # would clear url.url_type_id silently — we'd rather force the admin to
    # untangle deliberately.
    url_uses = Url.query.filter_by(url_type_id=url_type.id, is_deleted=False).count()
    if url_uses > 0:
        flash(
            f"Can't delete {name!r}: it's the type for {url_uses} URL"
            f"{'' if url_uses == 1 else 's'}. Reassign or delete those first."
        )
        return redirect(url_for('admin.url_types'))

    db.session.delete(url_type)
    db.session.commit()
    flash(f"Deleted URL type {name!r}.")
    return redirect(url_for('admin.url_types'))
