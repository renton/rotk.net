import os
import re

from flask import render_template, redirect, url_for, flash, current_app, abort, request, jsonify
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import SubmitField

from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import db
from app.models import User, Chapter, Character, Faction, Role, Tag, TagAssociation, Url, UrlType, Event, EventType, Location, LocationType, Edit, MatchExclusion, ChapterHiddenSnippet, Annotation, Relationship, RelationshipType
from app.models.character import Portrait, PORTRAIT_DIR
from app.models.year_map import YearMap, YEARMAP_DIR, YEARMAP_FIRST_YEAR, YEARMAP_LAST_YEAR
from werkzeug.utils import secure_filename
from app.blueprints.main.views import _detect_image_type, _MAX_PORTRAIT_BYTES
from tools.decorators import admin_required
from tools.book_parser import find_character_mentions, find_event_mentions, find_location_mentions, count_mentions_per_character, strip_html_tags, build_needle_pattern, load_match_exclusions, load_chapter_keywords, load_chapter_character_summaries, split_keywords_csv, find_location_character_overlap, find_shared_needle_ids, location_needles, recount_character_book_mentions, apply_hidden_snippets, strip_and_normalize_with_html_map, _hidden_snippet_context, _WS_RE
from .forms import EditTagForm, CreateUserForm, EditUrlTypeForm, EditEventTypeForm, EditLocationTypeForm, EditRelationshipTypeForm
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


@admin.route('/users/<int:user_id>/delete', methods=['GET', 'POST'])
@login_required
@admin_required
def delete_user(user_id):
    target = User.query.get_or_404(user_id)

    if target.id == current_user.id:
        flash("You can't delete your own account. Ask another admin.")
        return redirect(url_for('admin.users'))

    if target.is_administrator:
        remaining_admins = User.query.filter(
            User.is_administrator.is_(True),
            User.id != target.id,
        ).count()
        if remaining_admins == 0:
            flash("Can't delete the last administrator.")
            return redirect(url_for('admin.users'))

    form = _CsrfOnlyForm()

    if form.validate_on_submit():
        username = target.username
        db.session.delete(target)
        db.session.commit()
        flash(f"Deleted user {username}. Their username and email are available for reuse.")
        return redirect(url_for('admin.users'))

    return render_template(
        'admin/delete_user.html',
        target=target,
        csrf_form=form,
    )
# ----- Chapter ↔ Character association editor -----------------------------

@admin.route('/chapter-dates', methods=['GET', 'POST'])
@login_required
@admin_required
def chapter_dates():
    """Bulk-edit the free-form `date` string on every chapter.

    Single page lists all chapters in order with an input per row.
    POST persists only the rows whose date string actually changed,
    so the Edit audit log isn't flooded with no-op writes on every
    save."""
    chapters = Chapter.query.order_by(Chapter.chapter_num).all()
    csrf_form = _CsrfOnlyForm()

    if request.method == 'POST':
        if not csrf_form.validate_on_submit():
            abort(400)
        updated = 0
        for chapter in chapters:
            new_value = (request.form.get(f'date_{chapter.id}') or '').strip()
            if new_value != (chapter.date or ''):
                chapter.date = new_value
                updated += 1
        if updated:
            db.session.commit()
            flash(f"Updated dates on {updated} chapter{'s' if updated != 1 else ''}.")
        else:
            flash("No changes.")
        return redirect(url_for('admin.chapter_dates'))

    return render_template(
        'admin/chapter_dates.html',
        chapters=chapters,
        csrf_form=csrf_form,
    )


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

        # The M2M doesn't filter `is_deleted` — drop soft-deleted
        # characters here so they don't appear in the listing.
        associated = sorted(
            (c for c in selected.characters if not c.is_deleted),
            key=lambda c: c.name,
        )
        # Per-(chapter, character) keyword overrides for this chapter.
        per_char_kw = load_chapter_keywords(selected.id, 'chapter_character', 'character_id')
        per_char_summary = load_chapter_character_summaries(selected.id)
        seen_factions = {}
        for character in associated:
            exclusions = load_match_exclusions(selected.id, 'character', character.id)
            kw_csv = per_char_kw.get(character.id, '')
            needles = split_keywords_csv(kw_csv) or character.get_all_name_labels()
            # Live (still-tagged) mentions — filter out fingerprints the
            # admin has already excluded so the live pool reflects what
            # actually renders in the prose.
            live = find_character_mentions(selected, character, limit=None,
                                           exclusions=exclusions, needles=needles)
            excluded_rows = MatchExclusion.query.filter_by(
                chapter_id=selected.id,
                target_type='character',
                target_id=character.id,
            ).order_by(MatchExclusion.id).all()
            rows.append({
                'character': character,
                'mentions': live,
                'mention_count': len(live),
                'excluded': excluded_rows,
                'roles': list(character.roles),
                'faction': character.primary_faction,
                'keywords': kw_csv,
                'summary': per_char_summary.get(character.id, ''),
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

    # Per-chapter warning signals — same shape the public chapter view
    # uses to render red/green icons on inline pills. Surfacing them
    # here so admins can spot the same ambiguity at a glance from the
    # association listing.
    #
    #   in_chapter_dup_ids      : ids of characters sharing at least one
    #                             needle (name / courtesy / alias) with
    #                             ANOTHER character TAGGED IN THIS
    #                             chapter. Needle-based (not name-only)
    #                             so e.g. two characters whose aliases
    #                             both include "Yu" both get flagged.
    #   loc_overlap_by_char_id  : dict[character.id -> list[Location]]
    #                             of cross-type needle overlaps. Templates
    #                             use the list to name the matched
    #                             locations in the hover tooltip.
    in_chapter_dup_ids = set()
    loc_overlap_by_char_id = {}
    if selected is not None:
        chapter_chars = [r['character'] for r in rows]
        # Use the SAME chapter-scoped keywords the inline tagger uses
        # (chapter_character.keywords / chapter_location.keywords when
        # set, else the entity's global labels). Pure-global aliases
        # produce green-icon overlaps that don't reflect what's
        # actually tagged in the prose.
        char_kw_csv_by_id = {r['character'].id: r['keywords'] for r in rows}
        def _char_needles(c):
            return (split_keywords_csv(char_kw_csv_by_id.get(c.id, ''))
                    or c.get_all_name_labels())
        chapter_locs = [l for l in selected.locations if not l.is_deleted]
        loc_kw_lookup = load_chapter_keywords(
            selected.id, 'chapter_location', 'location_id',
        )
        def _loc_needles(loc):
            return (split_keywords_csv(loc_kw_lookup.get(loc.id, ''))
                    or location_needles(loc))
        in_chapter_dup_ids = find_shared_needle_ids(chapter_chars, _char_needles)
        _loc_map, loc_overlap_by_char_id = find_location_character_overlap(
            chapter_locs, chapter_chars,
            location_needles_for=_loc_needles,
            character_needles_for=_char_needles,
        )

    return render_template(
        'admin/chapter_associations.html',
        chapters=chapters,
        selected=selected,
        rows=rows,
        faction_options=faction_options,
        all_characters=all_characters,
        duplicate_names=duplicate_names,
        in_chapter_dup_ids=in_chapter_dup_ids,
        loc_overlap_by_char_id=loc_overlap_by_char_id,
        factions_by_char=factions_by_char,
        roles_by_char=roles_by_char,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/chapter-associations/<int:chapter_num>/<int:character_id>/summary', methods=['POST'])
@login_required
@admin_required
def chapter_associations_summary(chapter_num, character_id):
    """Write the per-(chapter, character) `summary` text. Empty string
    clears it. Idempotent — re-posting the same value is a no-op."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    character = Character.query.get_or_404(character_id)
    if character not in chapter.characters:
        flash(f"{character.name!r} is not associated with chapter "
              f"{chapter.chapter_num}; can't save a summary.")
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    new_summary = (request.form.get('summary') or '').strip()
    # Direct UPDATE on the association row — same pattern the keyword
    # writer uses (no ORM mapping on the chapter_character M2M).
    from sqlalchemy import text
    db.session.execute(
        text("UPDATE chapter_character SET summary = :s "
             "WHERE chapter_id = :cid AND character_id = :charid"),
        {'s': new_summary, 'cid': chapter.id, 'charid': character.id},
    )
    db.session.commit()
    flash(f"Saved chapter-{chapter.chapter_num} summary for "
          f"{character.name!r}.")
    # Anchor back at the row that was just edited so the admin lands
    # right where they started.
    return redirect(
        url_for('admin.chapter_associations', chapter_num=chapter_num)
        + f'#assoc-row-{character_id}'
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
        # Recount this character's book_mention_count from scratch:
        # they have one fewer chapter to count from now. Done in the
        # same transaction as the M2M remove.
        recount_character_book_mentions(character)
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
    """Add or resync a Character ↔ Chapter association.

    Stores the submitted keyword list on the per-association row
    (chapter_character.keywords) for THIS chapter only. The character's
    global `aliases` field is no longer touched.

    Two flows:
    * Fresh add — pair isn't yet linked: link the pair AND set
      chapter_character.keywords to the submitted (matched) list.
    * Resync — pair already linked: REPLACE chapter_character.keywords
      with the submitted (matched) list. Other chapters' keyword rows
      for this character are unaffected.

    Per-snippet MatchExclusion rows for this (chapter, character) pair
    are never touched — the admin's deliberate "this snippet is wrong"
    decisions persist across resyncs.

    Backwards compat: the older single `search_term` field name is also
    accepted, treated as a one-keyword list."""
    from tools.book_parser import strip_html_tags, build_needle_pattern
    from app.models.character import Character as _Char
    from sqlalchemy import text

    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()

    character, err = _resolve_character_from_form()
    if err:
        flash(err)
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    raw_terms = (request.form.get('search_terms') or request.form.get('search_term') or '').strip()
    keywords = [k.strip() for k in raw_terms.split(',') if k.strip()]
    if not keywords:
        flash("Enter at least one keyword (comma-separated for multiple).")
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    content = strip_html_tags(chapter.content)

    # First pass: keep only keywords that actually occur in this chapter.
    matched = []
    no_match = []
    total_matches = 0
    for keyword in keywords:
        n = len(build_needle_pattern([keyword]).findall(content))
        if n == 0:
            no_match.append(keyword)
            continue
        total_matches += n
        matched.append(keyword)

    # Dedup matched while preserving order.
    seen = set()
    new_kw_list = []
    for kw in matched:
        if kw not in seen:
            seen.add(kw)
            new_kw_list.append(kw)
    new_kw_csv = ','.join(new_kw_list)

    is_resync = character in chapter.characters
    if not is_resync:
        chapter.characters.append(character)
        db.session.flush()  # ensure the row exists before the UPDATE below

    db.session.execute(
        text(
            "UPDATE chapter_character SET keywords = :kw "
            "WHERE chapter_id = :cid AND character_id = :charid"
        ),
        {'kw': new_kw_csv, 'cid': chapter.id, 'charid': character.id},
    )

    # Recount this character's book_mention_count from scratch — both
    # paths above (fresh add, keyword resync) can change which matches
    # are counted, so re-query their chapter_character rows and re-sum.
    recount_character_book_mentions(character)

    db.session.commit()

    parts = []
    if total_matches:
        parts.append(f"Found {total_matches} occurrence{'' if total_matches == 1 else 's'} across {len(matched)} keyword(s).")
    if is_resync:
        parts.append(
            f"Resynced keywords for {character.name!r} in this chapter: "
            f"now {new_kw_csv or '(empty)'}."
        )
    else:
        parts.append(
            f"{character.name!r} is now associated with chapter {chapter.chapter_num} "
            f"(keywords: {new_kw_csv or '(empty)'})."
        )
    if no_match:
        parts.append("Skipped (not found in chapter): " + ", ".join(repr(k) for k in no_match) + ".")
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

    # Both characters' chapter sets changed — recount each from scratch
    # so book_mention_count picks up the swap.
    recount_character_book_mentions(old_character)
    recount_character_book_mentions(new_character)

    db.session.commit()

    flash(
        f"Switched {old_character.name} → {new_character.name} in "
        f"chapter {chapter.chapter_num}."
    )
    return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))


@admin.route('/chapter-associations/<int:chapter_num>/<int:character_id>/exclude', methods=['POST'])
@login_required
@admin_required
def chapter_associations_exclude(chapter_num, character_id):
    """Mark a single snippet as a bad match for this (chapter, character).
    Same shape as location_associations_exclude — the underlying
    MatchExclusion table is polymorphic via target_type."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    character = Character.query.get_or_404(character_id)

    match_text = (request.form.get('match_text') or '').strip()
    before = request.form.get('before_snippet') or ''
    after = request.form.get('after_snippet') or ''
    if not match_text:
        msg = "Snippet fingerprint missing — refresh the page and try again."
        if _wants_json():
            return jsonify(error=msg), 400
        flash(msg)
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    existing = MatchExclusion.query.filter_by(
        chapter_id=chapter.id,
        target_type='character',
        target_id=character.id,
        match_text=match_text,
        before_snippet=before,
        after_snippet=after,
    ).first()
    if existing is None:
        row = MatchExclusion(
            chapter_id=chapter.id,
            target_type='character',
            target_id=character.id,
            match_text=match_text,
            before_snippet=before,
            after_snippet=after,
        )
        db.session.add(row)
        db.session.commit()
    else:
        row = existing

    if _wants_json():
        return jsonify(
            id=row.id,
            match_text=row.match_text,
            before_snippet=row.before_snippet,
            after_snippet=row.after_snippet,
        )

    flash(f"Excluded snippet {match_text!r} for {character.name!r} in chapter {chapter.chapter_num}.")
    return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))


@admin.route('/chapter-associations/<int:chapter_num>/<int:character_id>/restore/<int:exclusion_id>', methods=['POST'])
@login_required
@admin_required
def chapter_associations_restore(chapter_num, character_id, exclusion_id):
    """Undo a previous per-snippet exclusion — re-show the match."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    row = MatchExclusion.query.get_or_404(exclusion_id)
    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    if (row.chapter_id != chapter.id or row.target_type != 'character' or
            row.target_id != character_id):
        abort(404)

    match_text = row.match_text
    before = row.before_snippet
    after = row.after_snippet
    db.session.delete(row)
    db.session.commit()

    if _wants_json():
        return jsonify(
            ok=True,
            match_text=match_text,
            before_snippet=before,
            after_snippet=after,
        )

    flash(f"Restored snippet {match_text!r}.")
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


# ----- Chapter Edit (hide-snippet tool) -----------------------------------

@admin.route('/chapter-edit', methods=['GET'])
@admin.route('/chapter-edit/<int:chapter_num>', methods=['GET'])
@login_required
@admin_required
def chapter_edit(chapter_num=None):
    """Chapter-editing admin page. Read-only view of the chapter's
    prose PLUS a highlight-and-hide affordance for suppressing bad
    snippets from the public reader. Prose can't be edited / added
    to / deleted from — the ONLY mutation this page supports is
    marking spans as hidden (or un-hiding previously marked ones)."""
    if chapter_num is None:
        # Allow GET-form ?chapter_num=N submissions to redirect to
        # the path-style URL so the page is shareable.
        from_query = request.args.get('chapter_num', type=int)
        if from_query is not None:
            return redirect(url_for('admin.chapter_edit', chapter_num=from_query))

    chapters = Chapter.query.order_by(Chapter.chapter_num).all()
    selected = None
    rendered_content = ''
    hidden_rows = []

    if chapter_num is not None:
        selected = Chapter.query.filter_by(chapter_num=chapter_num).first()
        if selected is None:
            abort(404)
        hidden_rows = (
            ChapterHiddenSnippet.query
            .filter_by(chapter_id=selected.id)
            .order_by(ChapterHiddenSnippet.id)
            .all()
        )
        # Wrap hidden spans in <s> for the admin view; public chapter
        # view uses admin=False to REMOVE them entirely.
        rendered_content = apply_hidden_snippets(selected.content, hidden_rows, admin=True)

    return render_template(
        'admin/chapter_edit.html',
        chapters=chapters,
        selected=selected,
        rendered_content=rendered_content,
        hidden_rows=hidden_rows,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/chapter-edit/<int:chapter_num>/hide', methods=['POST'])
@login_required
@admin_required
def chapter_edit_hide(chapter_num):
    """Persist a new hidden snippet for this chapter.

    Client POSTs: match_text (the selected prose, plain text), plus
    100+ chars of context on each side (before, after). Server
    normalises whitespace, trims to the same 60-char / word-boundary
    context find_*_mentions uses, and stores the fingerprint. Returns
    the new row's id (JSON) so the client-side JS can wire up the
    Restore affordance on the wrapped element.
    """
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()

    raw_match = (request.form.get('match_text') or '').strip()
    raw_before = request.form.get('before') or ''
    raw_after = request.form.get('after') or ''
    if not raw_match:
        return jsonify(error="Empty selection."), 400

    # Normalise the client's text — collapse whitespace and match
    # exactly what strip_and_normalize_with_html_map produces at
    # render time.
    match_text = _WS_RE.sub(' ', raw_match).strip()

    # We want to find where in the CURRENT chapter content this
    # selection lives, so we can compute the same trimmed
    # (before, after) fingerprint the render pass will look for.
    # The client sent generous context; use that to disambiguate
    # when the selection appears multiple times in the chapter.
    normalized, _positions = strip_and_normalize_with_html_map(chapter.content)
    if not match_text or not normalized:
        return jsonify(error="Match not found in chapter content."), 400

    # Normalise the client-side context the same way we normalise the
    # chapter content, then use it to pick the right occurrence when
    # match_text appears more than once.
    client_before = _WS_RE.sub(' ', raw_before).strip()
    client_after = _WS_RE.sub(' ', raw_after).strip()

    best_idx = -1
    start = 0
    while True:
        idx = normalized.find(match_text, start)
        if idx < 0:
            break
        # Compare surrounding text against what the client sent — a
        # loose "endswith / startswith" so trailing/leading noise
        # doesn't disqualify.
        actual_before = normalized[max(0, idx - len(client_before)):idx]
        actual_after = normalized[idx + len(match_text):idx + len(match_text) + len(client_after)]
        if (not client_before or actual_before.endswith(client_before[-40:])) and \
           (not client_after or actual_after.startswith(client_after[:40])):
            best_idx = idx
            break
        start = idx + 1

    if best_idx < 0:
        # Fallback: just take the first occurrence. Client's context
        # didn't match — usually a whitespace quirk.
        best_idx = normalized.find(match_text)
        if best_idx < 0:
            return jsonify(error="Selection not found in chapter content."), 400

    before, after = _hidden_snippet_context(normalized, best_idx, len(match_text))

    # Idempotency: if an identical fingerprint already exists, return
    # its id without inserting again.
    existing = ChapterHiddenSnippet.query.filter_by(
        chapter_id=chapter.id,
        match_text=match_text,
        before_snippet=before,
        after_snippet=after,
    ).first()
    if existing is None:
        row = ChapterHiddenSnippet(
            chapter_id=chapter.id,
            match_text=match_text,
            before_snippet=before,
            after_snippet=after,
        )
        db.session.add(row)
        db.session.commit()
    else:
        row = existing

    return jsonify(id=row.id, match_text=row.match_text)


@admin.route('/chapter-edit/<int:chapter_num>/restore/<int:snippet_id>', methods=['POST'])
@login_required
@admin_required
def chapter_edit_restore(chapter_num, snippet_id):
    """Un-hide a previously stored ChapterHiddenSnippet — the row is
    deleted, and the next render (admin + public) shows the prose again."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    row = ChapterHiddenSnippet.query.get_or_404(snippet_id)
    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    if row.chapter_id != chapter.id:
        abort(404)

    db.session.delete(row)
    db.session.commit()
    return jsonify(ok=True)


# ----- Chapter ↔ Event association editor ---------------------------------

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
        per_event_kw = load_chapter_keywords(selected.id, 'event_chapter', 'event_id')
        for event in associated:
            kw_csv = per_event_kw.get(event.id, '')
            needles = split_keywords_csv(kw_csv)
            if not needles:
                needles = [event.name] + [a.strip() for a in (event.aliases or '').split(',') if a.strip()]
            mentions = find_event_mentions(selected, event, limit=None, needles=needles)
            rows.append({
                'event': event,
                'mentions': mentions,
                'mention_count': len(mentions),
                'location': event.location,
                'keywords': kw_csv,
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
    """Attach an Event to a chapter and set its per-chapter keywords.

    Stores `search_terms` on the event_chapter.keywords row for THIS
    chapter only (resync). Empty keyword list is fine — the event is
    still linked (shows in the chapter sidebar) but no inline tagging.
    Keywords that don't appear in the chapter are reported and
    skipped."""
    from sqlalchemy import text

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

    content = strip_html_tags(chapter.content)
    matched = []
    no_match = []
    for keyword in keywords:
        if build_needle_pattern([keyword]).findall(content):
            matched.append(keyword)
        else:
            no_match.append(keyword)
    # Dedup preserving order.
    seen = set()
    deduped = []
    for kw in matched:
        if kw not in seen:
            seen.add(kw)
            deduped.append(kw)
    new_kw_csv = ','.join(deduped)

    is_resync = event in chapter.events
    if not is_resync:
        chapter.events.append(event)
        db.session.flush()

    db.session.execute(
        text(
            "UPDATE event_chapter SET keywords = :kw "
            "WHERE event_id = :eid AND chapter_id = :cid"
        ),
        {'kw': new_kw_csv, 'eid': event.id, 'cid': chapter.id},
    )

    db.session.commit()

    parts = []
    if is_resync:
        parts.append(
            f"Resynced keywords for {event.name!r} in this chapter: "
            f"now {new_kw_csv or '(empty)'}."
        )
    else:
        parts.append(
            f"{event.name!r} is now associated with chapter {chapter.chapter_num} "
            f"(keywords: {new_kw_csv or '(empty)'})."
        )
    if no_match:
        parts.append("Skipped (not found in chapter): " + ", ".join(repr(k) for k in no_match) + ".")
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


# ----- Chapter ↔ Location association editor ------------------------------

def _resolve_location_from_form():
    raw_id = (request.form.get('location_id') or '').strip()
    raw_name = (request.form.get('location_name') or '').strip()

    if raw_id.isdigit():
        loc = Location.query.get(int(raw_id))
        if loc is None:
            return None, "Couldn't find a location with that id."
        return loc, None

    if raw_name:
        m = _ID_SUFFIX_RE.search(raw_name)
        if m:
            loc = Location.query.get(int(m.group(1)))
            if loc is None:
                return None, "Couldn't find a location with that id."
            return loc, None
        matches = Location.query.filter(Location.name == raw_name).all()
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, (
                f"Multiple locations named {raw_name!r}. Pick from the dropdown "
                f"(each option carries a unique '#<id>' suffix)."
            )
    return None, "Couldn't find a location matching that selection."


@admin.route('/location-associations', methods=['GET'])
@admin.route('/location-associations/<int:chapter_num>', methods=['GET'])
@login_required
@admin_required
def location_associations(chapter_num=None):
    """Mirror of chapter_associations / event_associations but for the
    chapter ↔ location M2M (which is independent of event-pinned
    locations — those still show up automatically in the chapter sidebar
    via the events that pin to them)."""
    if chapter_num is None:
        from_query = request.args.get('chapter_num', type=int)
        if from_query is not None:
            return redirect(url_for('admin.location_associations', chapter_num=from_query))

    chapters = Chapter.query.order_by(Chapter.chapter_num).all()
    selected = None
    rows = []
    all_locations = []

    if chapter_num is not None:
        selected = Chapter.query.filter_by(chapter_num=chapter_num).first()
        if selected is None:
            abort(404)

        # Drop soft-deleted locations — the M2M relationship doesn't
        # filter `is_deleted` so deleted rows would otherwise still
        # appear in the listing.
        associated = sorted(
            (l for l in selected.locations if not l.is_deleted),
            key=lambda l: l.name,
        )
        per_loc_kw = load_chapter_keywords(selected.id, 'chapter_location', 'location_id')
        for loc in associated:
            exclusions = load_match_exclusions(selected.id, 'location', loc.id)
            kw_csv = per_loc_kw.get(loc.id, '')
            needles = split_keywords_csv(kw_csv)
            if not needles:
                needles = [loc.name] + [a.strip() for a in (loc.aliases or '').split(',') if a.strip()]
            # Live (still-tagged) mentions — filter via the exclusions set
            # so snippets already marked-bad don't appear in the main list.
            live = find_location_mentions(selected, loc, limit=None,
                                          exclusions=exclusions, needles=needles)
            # Stored exclusion rows for this (chapter, location) — used
            # to render the collapsible "Excluded snippets" section with
            # restore buttons.
            excluded_rows = MatchExclusion.query.filter_by(
                chapter_id=selected.id,
                target_type='location',
                target_id=loc.id,
            ).order_by(MatchExclusion.id).all()
            rows.append({
                'location': loc,
                'mentions': live,
                'mention_count': len(live),
                'excluded': excluded_rows,
                'keywords': kw_csv,
            })

        all_locations = (
            Location.query
            .filter(Location.is_deleted.is_(False))
            .order_by(Location.name)
            .all()
        )

    # Same warning signals as chapter_associations, swapped sides.
    #
    #   in_chapter_dup_ids      : ids of locations sharing at least one
    #                             needle (name or alias) with ANOTHER
    #                             location TAGGED IN THIS chapter. This
    #                             is the canonical case for the admin-
    #                             division import — "Yu Province" and
    #                             "Yu County" both carry the alias "Yu"
    #                             so a name-only check missed them.
    #   char_overlap_by_loc_id  : dict[location.id -> list[Character]]
    #                             of cross-type needle overlaps. Templates
    #                             use the list to name the matched
    #                             characters in the hover tooltip.
    in_chapter_dup_ids = set()
    char_overlap_by_loc_id = {}
    if selected is not None:
        chapter_locs = [r['location'] for r in rows]
        loc_kw_csv_by_id = {r['location'].id: r['keywords'] for r in rows}
        def _loc_needles(loc):
            return (split_keywords_csv(loc_kw_csv_by_id.get(loc.id, ''))
                    or location_needles(loc))
        chapter_chars = [c for c in selected.characters if not c.is_deleted]
        char_kw_lookup = load_chapter_keywords(
            selected.id, 'chapter_character', 'character_id',
        )
        def _char_needles(c):
            return (split_keywords_csv(char_kw_lookup.get(c.id, ''))
                    or c.get_all_name_labels())
        in_chapter_dup_ids = find_shared_needle_ids(chapter_locs, _loc_needles)
        char_overlap_by_loc_id, _char_map = find_location_character_overlap(
            chapter_locs, chapter_chars,
            location_needles_for=_loc_needles,
            character_needles_for=_char_needles,
        )

    return render_template(
        'admin/location_associations.html',
        chapters=chapters,
        selected=selected,
        rows=rows,
        all_locations=all_locations,
        in_chapter_dup_ids=in_chapter_dup_ids,
        char_overlap_by_loc_id=char_overlap_by_loc_id,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/location-associations/<int:chapter_num>/add', methods=['POST'])
@login_required
@admin_required
def location_associations_add(chapter_num):
    """Add or resync a Location ↔ Chapter association. Keywords are
    stored on the chapter_location row for THIS chapter only —
    location.aliases stays untouched. Empty keyword list is fine
    (location appears in sidebar but no inline tagging)."""
    from sqlalchemy import text

    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()

    loc, err = _resolve_location_from_form()
    if err:
        flash(err)
        return redirect(url_for('admin.location_associations', chapter_num=chapter_num))

    raw_terms = (request.form.get('search_terms') or '').strip()
    keywords = [k.strip() for k in raw_terms.split(',') if k.strip()]

    content = strip_html_tags(chapter.content)
    matched = []
    no_match = []
    for keyword in keywords:
        if build_needle_pattern([keyword]).findall(content):
            matched.append(keyword)
        else:
            no_match.append(keyword)
    seen = set()
    deduped = []
    for kw in matched:
        if kw not in seen:
            seen.add(kw)
            deduped.append(kw)
    new_kw_csv = ','.join(deduped)

    is_resync = loc in chapter.locations
    if not is_resync:
        chapter.locations.append(loc)
        db.session.flush()

    db.session.execute(
        text(
            "UPDATE chapter_location SET keywords = :kw "
            "WHERE chapter_id = :cid AND location_id = :lid"
        ),
        {'kw': new_kw_csv, 'cid': chapter.id, 'lid': loc.id},
    )

    db.session.commit()

    parts = []
    if is_resync:
        parts.append(
            f"Resynced keywords for {loc.name!r} in this chapter: "
            f"now {new_kw_csv or '(empty)'}."
        )
    else:
        parts.append(
            f"{loc.name!r} is now associated with chapter {chapter.chapter_num} "
            f"(keywords: {new_kw_csv or '(empty)'})."
        )
    if no_match:
        parts.append("Skipped (not found in chapter): " + ", ".join(repr(k) for k in no_match) + ".")
    flash(" ".join(parts))

    return redirect(url_for('admin.location_associations', chapter_num=chapter_num))


@admin.route('/location-associations/<int:chapter_num>/remove/<int:location_id>', methods=['POST'])
@login_required
@admin_required
def location_associations_remove(chapter_num, location_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    loc = Location.query.get_or_404(location_id)

    if loc in chapter.locations:
        chapter.locations.remove(loc)
        db.session.commit()
        flash(f"Removed {loc.name!r} from chapter {chapter.chapter_num}.")
    else:
        flash(f"{loc.name!r} was not associated with chapter {chapter.chapter_num}.")
    return redirect(url_for('admin.location_associations', chapter_num=chapter_num))


@admin.route('/location-associations/<int:chapter_num>/switch/<int:location_id>', methods=['POST'])
@login_required
@admin_required
def location_associations_switch(chapter_num, location_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    old_loc = Location.query.get_or_404(location_id)

    new_loc, err = _resolve_location_from_form()
    if err:
        flash(err)
        return redirect(url_for('admin.location_associations', chapter_num=chapter_num))

    if new_loc.id == old_loc.id:
        flash(f"{new_loc.name!r} is already the associated location.")
        return redirect(url_for('admin.location_associations', chapter_num=chapter_num))

    if old_loc in chapter.locations:
        chapter.locations.remove(old_loc)
    if new_loc not in chapter.locations:
        chapter.locations.append(new_loc)
    db.session.commit()

    flash(f"Switched {old_loc.name!r} → {new_loc.name!r} in chapter {chapter.chapter_num}.")
    return redirect(url_for('admin.location_associations', chapter_num=chapter_num))


def _wants_json():
    """The admin location-snippets JS posts these forms with
    `Accept: application/json` so it can swap the row between the
    live and excluded pools without a full page reload. Plain form
    submits fall through to the redirect-with-flash path."""
    return 'application/json' in (request.headers.get('Accept') or '')


@admin.route('/location-associations/<int:chapter_num>/<int:location_id>/exclude', methods=['POST'])
@login_required
@admin_required
def location_associations_exclude(chapter_num, location_id):
    """Mark a single snippet as a bad match for this (chapter, location).

    Admin posts the (before, match, after) fingerprint of the snippet
    they want suppressed. We store a MatchExclusion row; render-time
    scans + the admin page will hide that specific match. Duplicate
    posts are idempotent — the same fingerprint inserted twice is
    harmless, since the render-time set lookup dedupes by membership.

    Returns JSON when the client asks for it (Accept: application/json);
    falls back to the redirect-with-flash flow otherwise."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    location = Location.query.get_or_404(location_id)

    match_text = (request.form.get('match_text') or '').strip()
    before = request.form.get('before_snippet') or ''
    after = request.form.get('after_snippet') or ''
    if not match_text:
        msg = "Snippet fingerprint missing — refresh the page and try again."
        if _wants_json():
            return jsonify(error=msg), 400
        flash(msg)
        return redirect(url_for('admin.location_associations', chapter_num=chapter_num))

    # Idempotency: skip insert if an identical row already exists.
    existing = MatchExclusion.query.filter_by(
        chapter_id=chapter.id,
        target_type='location',
        target_id=location.id,
        match_text=match_text,
        before_snippet=before,
        after_snippet=after,
    ).first()
    if existing is None:
        row = MatchExclusion(
            chapter_id=chapter.id,
            target_type='location',
            target_id=location.id,
            match_text=match_text,
            before_snippet=before,
            after_snippet=after,
        )
        db.session.add(row)
        db.session.commit()
    else:
        row = existing

    if _wants_json():
        return jsonify(
            id=row.id,
            match_text=row.match_text,
            before_snippet=row.before_snippet,
            after_snippet=row.after_snippet,
        )

    flash(f"Excluded snippet {match_text!r} for {location.name!r} in chapter {chapter.chapter_num}.")
    return redirect(url_for('admin.location_associations', chapter_num=chapter_num))


@admin.route('/location-associations/<int:chapter_num>/<int:location_id>/restore/<int:exclusion_id>', methods=['POST'])
@login_required
@admin_required
def location_associations_restore(chapter_num, location_id, exclusion_id):
    """Undo a previous per-snippet exclusion — re-show the match."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    row = MatchExclusion.query.get_or_404(exclusion_id)
    # Sanity check: route params must match the row to prevent cross-
    # entity restore by URL-tampering. 404 keeps the failure mode quiet.
    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()
    if (row.chapter_id != chapter.id or row.target_type != 'location' or
            row.target_id != location_id):
        abort(404)

    match_text = row.match_text
    before = row.before_snippet
    after = row.after_snippet
    db.session.delete(row)
    db.session.commit()

    if _wants_json():
        return jsonify(
            ok=True,
            match_text=match_text,
            before_snippet=before,
            after_snippet=after,
        )

    flash(f"Restored snippet {match_text!r}.")
    return redirect(url_for('admin.location_associations', chapter_num=chapter_num))


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


# ----- Event Type manager -------------------------------------------------

_EVENT_TYPE_SORTS = ('name', 'created_at', 'event_count')
_EVENT_TYPES_PER_PAGE = 50


@admin.route('/event-types', methods=['GET'])
@login_required
@admin_required
def event_types():
    """List event types with their usage count, search + sort. Same
    shape as /admin/url-types."""
    page = request.args.get('page', 1, type=int)
    search = (request.args.get('q') or '').strip()
    sort = request.args.get('sort', 'name')
    direction = request.args.get('dir', 'asc')

    if sort not in _EVENT_TYPE_SORTS:
        sort = 'name'
    if direction not in ('asc', 'desc'):
        direction = 'asc'

    event_counts = (
        db.session.query(
            Event.event_type_id.label('event_type_id'),
            func.count(Event.id).label('event_count'),
        )
        .filter(Event.is_deleted.is_(False))
        .group_by(Event.event_type_id)
        .subquery()
    )
    event_count_expr = func.coalesce(event_counts.c.event_count, 0)

    query = (
        EventType.query
        .outerjoin(event_counts, EventType.id == event_counts.c.event_type_id)
        .add_columns(event_count_expr.label('event_count'))
        .filter(EventType.is_hidden.is_(False))
    )
    if search:
        query = query.filter(EventType.name.ilike(f"%{search}%"))

    if sort == 'event_count':
        order_col = event_count_expr
    else:
        order_col = getattr(EventType, sort)
    query = query.order_by(order_col.desc() if direction == 'desc' else order_col.asc())
    if sort != 'name':
        query = query.order_by(EventType.name.asc())

    pagination = query.paginate(page=page, per_page=_EVENT_TYPES_PER_PAGE, error_out=False)

    return render_template(
        'admin/event_types.html',
        pagination=pagination,
        search=search,
        sort=sort,
        direction=direction,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/event-types/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_event_type():
    form = EditEventTypeForm()
    if form.validate_on_submit():
        ev_type = EventType()
        form.populate_obj(ev_type)
        db.session.add(ev_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"An event type named {ev_type.name!r} already exists.")
            return redirect(url_for('admin.new_event_type'))
        flash(f"Created event type {ev_type.name!r}.")
        return redirect(url_for('admin.event_types'))

    return render_template('admin/event_type_edit.html', form=form, event_type=None)


@admin.route('/event-types/<int:event_type_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_event_type(event_type_id):
    ev_type = EventType.query.get_or_404(event_type_id)
    form = EditEventTypeForm(obj=ev_type)
    if form.validate_on_submit():
        form.populate_obj(ev_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"An event type named {ev_type.name!r} already exists.")
            return redirect(url_for('admin.edit_event_type', event_type_id=ev_type.id))
        flash(f"Updated event type {ev_type.name!r}.")
        return redirect(url_for('admin.event_types'))

    return render_template('admin/event_type_edit.html', form=form, event_type=ev_type)


@admin.route('/event-types/<int:event_type_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_event_type(event_type_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    ev_type = EventType.query.get_or_404(event_type_id)
    name = ev_type.name

    # Refuse if any Event still uses this type. FK is ON DELETE SET NULL
    # so cascading would silently strip the type — force the admin to
    # untangle on purpose.
    in_use = Event.query.filter_by(event_type_id=ev_type.id, is_deleted=False).count()
    if in_use > 0:
        flash(
            f"Can't delete {name!r}: it's assigned to {in_use} event"
            f"{'' if in_use == 1 else 's'}. Reassign or delete those first."
        )
        return redirect(url_for('admin.event_types'))

    db.session.delete(ev_type)
    db.session.commit()
    flash(f"Deleted event type {name!r}.")
    return redirect(url_for('admin.event_types'))


_LOCATION_TYPE_SORTS = ('name', 'created_at', 'location_count')
_LOCATION_TYPES_PER_PAGE = 50


@admin.route('/location-types', methods=['GET'])
@login_required
@admin_required
def location_types():
    """List location types with their usage count, search + sort. Same
    shape as /admin/event-types."""
    page = request.args.get('page', 1, type=int)
    search = (request.args.get('q') or '').strip()
    sort = request.args.get('sort', 'name')
    direction = request.args.get('dir', 'asc')

    if sort not in _LOCATION_TYPE_SORTS:
        sort = 'name'
    if direction not in ('asc', 'desc'):
        direction = 'asc'

    location_counts = (
        db.session.query(
            Location.location_type_id.label('location_type_id'),
            func.count(Location.id).label('location_count'),
        )
        .filter(Location.is_deleted.is_(False))
        .group_by(Location.location_type_id)
        .subquery()
    )
    location_count_expr = func.coalesce(location_counts.c.location_count, 0)

    query = (
        LocationType.query
        .outerjoin(location_counts, LocationType.id == location_counts.c.location_type_id)
        .add_columns(location_count_expr.label('location_count'))
        .filter(LocationType.is_hidden.is_(False))
    )
    if search:
        query = query.filter(LocationType.name.ilike(f"%{search}%"))

    if sort == 'location_count':
        order_col = location_count_expr
    else:
        order_col = getattr(LocationType, sort)
    query = query.order_by(order_col.desc() if direction == 'desc' else order_col.asc())
    if sort != 'name':
        query = query.order_by(LocationType.name.asc())

    pagination = query.paginate(page=page, per_page=_LOCATION_TYPES_PER_PAGE, error_out=False)

    return render_template(
        'admin/location_types.html',
        pagination=pagination,
        search=search,
        sort=sort,
        direction=direction,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/location-types/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_location_type():
    form = EditLocationTypeForm()
    if form.validate_on_submit():
        loc_type = LocationType()
        form.populate_obj(loc_type)
        db.session.add(loc_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A location type named {loc_type.name!r} already exists.")
            return redirect(url_for('admin.new_location_type'))
        flash(f"Created location type {loc_type.name!r}.")
        return redirect(url_for('admin.location_types'))

    return render_template('admin/location_type_edit.html', form=form, location_type=None)


@admin.route('/location-types/<int:location_type_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_location_type(location_type_id):
    loc_type = LocationType.query.get_or_404(location_type_id)
    form = EditLocationTypeForm(obj=loc_type)
    if form.validate_on_submit():
        form.populate_obj(loc_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A location type named {loc_type.name!r} already exists.")
            return redirect(url_for('admin.edit_location_type', location_type_id=loc_type.id))
        flash(f"Updated location type {loc_type.name!r}.")
        return redirect(url_for('admin.location_types'))

    return render_template('admin/location_type_edit.html', form=form, location_type=loc_type)


@admin.route('/location-types/<int:location_type_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_location_type(location_type_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    loc_type = LocationType.query.get_or_404(location_type_id)
    name = loc_type.name

    # Refuse if any Location still uses this type. FK is ON DELETE SET NULL
    # so cascading would silently strip the type — force the admin to
    # untangle on purpose. Same safety pattern as delete_event_type.
    in_use = Location.query.filter_by(location_type_id=loc_type.id, is_deleted=False).count()
    if in_use > 0:
        flash(
            f"Can't delete {name!r}: it's assigned to {in_use} location"
            f"{'' if in_use == 1 else 's'}. Reassign or delete those first."
        )
        return redirect(url_for('admin.location_types'))

    db.session.delete(loc_type)
    db.session.commit()
    flash(f"Deleted location type {name!r}.")
    return redirect(url_for('admin.location_types'))


# ----- Annotations --------------------------------------------------------

def _annotation_list(is_public):
    """Shared list-page renderer for public + private annotation admin
    pages. Stacks annotations by (chapter, section_text) — one row per
    thread, with a count. Filters: chapter_num, show_deleted (checkbox
    that inverts to show only soft-deleted rows). Sort: chapter or
    latest activity."""
    from sqlalchemy import func

    from app.models.annotation import annotation_character, annotation_location

    chapter_num = request.args.get('chapter_num', type=int)
    filter_character_id = request.args.get('character_id', type=int)
    filter_location_id = request.args.get('location_id', type=int)
    sort = request.args.get('sort', 'latest')
    direction = request.args.get('dir', 'desc')
    show_deleted = request.args.get('show_deleted') in ('1', 'true', 'on')
    if sort not in ('latest', 'chapter', 'count'):
        sort = 'latest'
    if direction not in ('asc', 'desc'):
        direction = 'desc'

    # Group by (chapter_id, section_text) — one stacked row per thread.
    subq = (
        db.session.query(
            Annotation.chapter_id.label('chapter_id'),
            Annotation.section_text.label('section_text'),
            func.count(Annotation.id).label('cnt'),
            func.max(Annotation.created_at).label('latest_at'),
        )
        .filter(Annotation.is_public.is_(is_public))
        .filter(Annotation.is_deleted.is_(show_deleted))
    )
    if chapter_num is not None:
        subq = subq.join(Chapter, Chapter.id == Annotation.chapter_id) \
                   .filter(Chapter.chapter_num == chapter_num)
    if filter_character_id is not None:
        subq = subq.join(annotation_character,
                         annotation_character.c.annotation_id == Annotation.id) \
                   .filter(annotation_character.c.character_id == filter_character_id)
    if filter_location_id is not None:
        subq = subq.join(annotation_location,
                         annotation_location.c.annotation_id == Annotation.id) \
                   .filter(annotation_location.c.location_id == filter_location_id)
    subq = subq.group_by(Annotation.chapter_id, Annotation.section_text)

    if sort == 'chapter':
        # Sub-select needs chapter_num for sorting; do it as a Python
        # sort after the group query since inline ordering on grouped
        # rows is awkward across SQLAlchemy versions.
        rows = subq.all()
        chapter_map = {c.id: c for c in Chapter.query.all()}
        rows = sorted(rows, key=lambda r: chapter_map[r.chapter_id].chapter_num,
                      reverse=(direction == 'desc'))
    elif sort == 'count':
        rows = subq.order_by(func.count(Annotation.id).desc() if direction == 'desc'
                             else func.count(Annotation.id).asc()).all()
    else:  # latest
        rows = subq.order_by(func.max(Annotation.created_at).desc() if direction == 'desc'
                             else func.max(Annotation.created_at).asc()).all()

    # Build a payload: for each row, the full thread + chapter info so
    # the admin-list modal can display it without a per-row query.
    from tools.book_parser import annotation_section_hash, character_pill_colours
    threads_by_key = {}
    chapter_by_id = {c.id: c for c in Chapter.query.all()}
    stacked_rows = []
    for r in rows:
        key = annotation_section_hash(r.section_text)
        thread_annotations = (
            Annotation.query
            .filter_by(chapter_id=r.chapter_id, section_text=r.section_text,
                       is_public=is_public, is_deleted=show_deleted)
            .order_by(Annotation.created_at)
            .all()
        )
        # Union of character / location refs across the thread (they're
        # identical per-annotation today, but union is future-proof).
        ref_chars = {}
        ref_locs = {}
        for a in thread_annotations:
            for c in a.characters:
                ref_chars[c.id] = c
            for l in a.locations:
                ref_locs[l.id] = l
        chapter_num_val = chapter_by_id[r.chapter_id].chapter_num if r.chapter_id in chapter_by_id else None
        char_payload = []
        for c in sorted(ref_chars.values(), key=lambda x: x.name):
            bg, font, border = character_pill_colours(c)
            char_payload.append({'id': c.id, 'name': c.name, 'bg': bg, 'font': font, 'border': border})
        loc_payload = [
            {'id': l.id, 'name': l.name}
            for l in sorted(ref_locs.values(), key=lambda x: x.name)
        ]
        threads_by_key[key] = {
            'section_text': r.section_text,
            'chapter_id': r.chapter_id,
            'chapter_num': chapter_num_val,
            'characters': char_payload,
            'locations': loc_payload,
            'thread': [
                {
                    'id': a.id, 'body': a.body, 'is_public': a.is_public,
                    'is_deleted': a.is_deleted,
                    'created_at': a.created_at.strftime('%Y-%m-%d %H:%M'),
                    'created_by': a.created_by,
                }
                for a in thread_annotations
            ],
        }
        stacked_rows.append({
            'section_key': key,
            'section_text': r.section_text,
            'chapter_id': r.chapter_id,
            'chapter_num': chapter_num_val,
            'count': r.cnt,
            'latest_at': r.latest_at,
            # First annotation's body — the thread opener is the best
            # one-line identity for a thread (replies usually reference
            # it), so the list previews that rather than the section
            # prose or the newest reply.
            'first_body': thread_annotations[0].body if thread_annotations else '',
            'characters': char_payload,
            'locations': loc_payload,
        })

    chapters = Chapter.query.order_by(Chapter.chapter_num).all()

    # Filter dropdown options: only entities actually referenced by
    # annotations of this type — a full character list would be huge.
    filter_characters = (
        db.session.query(Character)
        .join(annotation_character, annotation_character.c.character_id == Character.id)
        .join(Annotation, Annotation.id == annotation_character.c.annotation_id)
        .filter(Annotation.is_public.is_(is_public))
        .distinct().order_by(Character.name).all()
    )
    filter_locations = (
        db.session.query(Location)
        .join(annotation_location, annotation_location.c.location_id == Location.id)
        .join(Annotation, Annotation.id == annotation_location.c.annotation_id)
        .filter(Annotation.is_public.is_(is_public))
        .distinct().order_by(Location.name).all()
    )

    return render_template(
        'admin/annotations.html',
        stacked_rows=stacked_rows,
        threads_by_key=threads_by_key,
        chapters=chapters,
        selected_chapter_num=chapter_num,
        sort=sort,
        direction=direction,
        show_deleted=show_deleted,
        is_public=is_public,
        filter_characters=filter_characters,
        filter_locations=filter_locations,
        filter_character_id=filter_character_id,
        filter_location_id=filter_location_id,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/annotations/public', methods=['GET'])
@login_required
@admin_required
def annotations_public():
    return _annotation_list(is_public=True)


@admin.route('/annotations/private', methods=['GET'])
@login_required
@admin_required
def annotations_private():
    return _annotation_list(is_public=False)


@admin.route('/annotations/create', methods=['POST'])
@login_required
@admin_required
def annotation_create():
    """Create a new annotation. Called from the chapter view modal
    and from the admin list pages' Add-to-thread button.

    Payload: chapter_id, section_text (full paragraph text; server
    normalises), body, is_public. Returns JSON with the new row's id
    + rendered fields for the client to append into the current thread."""
    from tools.book_parser import normalize_paragraph_text

    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter_id = request.form.get('chapter_id', type=int)
    section_text = (request.form.get('section_text') or '').strip()
    body = (request.form.get('body') or '').strip()
    is_public = request.form.get('is_public') in ('1', 'true', 'True', 'on')
    if not chapter_id or not section_text or not body:
        return jsonify(error="chapter_id, section_text, body are required."), 400
    chapter = Chapter.query.get(chapter_id)
    if chapter is None:
        return jsonify(error="chapter not found."), 404

    # Normalise section_text so lookups by paragraph work regardless
    # of whitespace quirks in the source form data.
    section_text = normalize_paragraph_text(section_text)

    row = Annotation(
        chapter_id=chapter.id,
        section_text=section_text,
        body=body,
        is_public=is_public,
    )
    # Auto-attach character / location references found in the section
    # text. Redundant across a thread (every annotation on the same
    # section carries the same refs) — accepted for now; makes filter
    # queries trivial.
    from tools.book_parser import detect_annotation_refs
    ref_chars, ref_locs = detect_annotation_refs(chapter, section_text)
    row.characters = ref_chars
    row.locations = ref_locs
    db.session.add(row)
    db.session.commit()

    return jsonify(
        id=row.id,
        body=row.body,
        created_at=row.created_at.strftime('%Y-%m-%d %H:%M'),
        created_by=row.created_by,
        is_public=row.is_public,
    )


@admin.route('/annotations/<int:annotation_id>/delete', methods=['POST'])
@login_required
@admin_required
def annotation_delete(annotation_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    row = Annotation.query.get_or_404(annotation_id)
    # Soft delete — flip the flag so an admin can find + restore
    # from the "show deleted" view on the list pages.
    row.is_deleted = True
    db.session.commit()

    if _wants_json():
        return jsonify(ok=True)

    dest = 'admin.annotations_public' if row.is_public else 'admin.annotations_private'
    flash("Annotation deleted.")
    return redirect(url_for(dest))


@admin.route('/annotations/close-thread', methods=['POST'])
@login_required
@admin_required
def annotation_close_thread():
    """Soft-delete EVERY private annotation on one (chapter, section)
    thread — the "Close" button on the private annotations list.
    Public annotations on the same section are untouched."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter_id = request.form.get('chapter_id', type=int)
    section_text = request.form.get('section_text') or ''
    if not chapter_id or not section_text:
        abort(400)

    rows = (
        Annotation.query
        .filter_by(chapter_id=chapter_id, section_text=section_text,
                   is_public=False, is_deleted=False)
        .all()
    )
    for r in rows:
        r.is_deleted = True
    db.session.commit()

    flash(f"Closed thread — {len(rows)} private annotation{'' if len(rows) == 1 else 's'} deleted.")
    return redirect(url_for('admin.annotations_private'))


@admin.route('/annotations/<int:annotation_id>/restore', methods=['POST'])
@login_required
@admin_required
def annotation_restore(annotation_id):
    """Undo a soft-delete."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    row = Annotation.query.get_or_404(annotation_id)
    row.is_deleted = False
    db.session.commit()

    if _wants_json():
        return jsonify(ok=True)

    dest = 'admin.annotations_public' if row.is_public else 'admin.annotations_private'
    flash("Annotation restored.")
    return redirect(url_for(dest))


# ---------------------------------------------------------------------------
# Yearly Maps — one territory-map image per year (184–280 AD)
# ---------------------------------------------------------------------------

@admin.route('/yearly-maps', methods=['GET'])
@login_required
@admin_required
def yearly_maps():
    """Grid of every year in the covered era (184–280) with its uploaded
    map image, if any. One image per year — `year` is unique on YearMap,
    so uploading again replaces the previous image."""
    maps_by_year = {
        m.year: m
        for m in YearMap.query.options(selectinload(YearMap.factions)).all()
    }
    picker_factions = (
        Faction.query
        .filter(Faction.is_hidden.is_(False))
        .order_by(Faction.name)
        .all()
    )
    # Modal prefill: the Edit button carries the year's current faction
    # set as JSON (Jinja can't build dict lists inline). Colours follow
    # badge_widget semantics — default_colour (#ffffff) means "unset",
    # shipped as None so the JS falls back to the Bootstrap-primary chip.
    def _chip(f):
        return {
            'id': f.id,
            'name': f.name,
            'font': f.font_colour,
            'bg': None if f.bg_colour == f.default_colour else f.bg_colour,
            'border': None if f.border_colour == f.default_colour else f.border_colour,
        }
    modal_factions_by_year = {
        year: [_chip(f) for f in m.factions]
        for year, m in maps_by_year.items()
    }
    return render_template(
        'admin/yearly_maps.html',
        years=range(YEARMAP_FIRST_YEAR, YEARMAP_LAST_YEAR + 1),
        maps_by_year=maps_by_year,
        picker_factions=picker_factions,
        modal_factions_by_year=modal_factions_by_year,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/yearly-maps/<int:year>/upload', methods=['POST'])
@login_required
@admin_required
def yearly_maps_upload(year):
    """Save the map image and/or attribution for one year.

    Posted from the Yearly Maps modal. The image file is REQUIRED when the
    year has no map yet, and OPTIONAL when one exists — omitting it updates
    only the attribution (source_site / source_url, Portrait's credit pair).

    File handling has the same defense-in-depth as the portrait uploader
    (main.upload_portrait): CSRF, per-file size cap, magic-byte sniffing,
    declared-extension consistency, server-constructed filename,
    path-containment check.
    """
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    if not (YEARMAP_FIRST_YEAR <= year <= YEARMAP_LAST_YEAR):
        abort(404)

    row = YearMap.query.filter_by(year=year).first()

    source_site = (request.form.get('source_site') or '').strip()
    source_url = (request.form.get('source_url') or '').strip()
    if len(source_site) > 255 or len(source_url) > 2048:
        flash("Attribution too long (site max 255, URL max 2048 characters).")
        return redirect(url_for('admin.yearly_maps'))

    # Factions present on this year's map. The modal's chip list ships
    # the FULL set as a CSV of ids in `faction_ids`, so the M2M is
    # replaced wholesale — removals are just absent ids.
    raw_faction_ids = (request.form.get('faction_ids') or '').strip()
    faction_ids = []
    for part in raw_faction_ids.split(','):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            flash(f"Bad faction id {part!r} in the factions list.")
            return redirect(url_for('admin.yearly_maps'))
        faction_ids.append(int(part))
    factions = []
    if faction_ids:
        factions = Faction.query.filter(Faction.id.in_(faction_ids)).all()
        if len(factions) != len(set(faction_ids)):
            flash("One or more factions in the list no longer exist.")
            return redirect(url_for('admin.yearly_maps'))

    file = request.files.get('image_file')
    has_file = file is not None and bool(file.filename)
    if not has_file and row is None:
        flash(f"No image on file for {year} AD — choose a file to upload.")
        return redirect(url_for('admin.yearly_maps'))

    if has_file:
        # ---- Size check --------------------------------------------------
        file.stream.seek(0, os.SEEK_END)
        size = file.stream.tell()
        file.stream.seek(0)
        if size <= 0:
            flash("Uploaded file is empty.")
            return redirect(url_for('admin.yearly_maps'))
        if size > _MAX_PORTRAIT_BYTES:
            flash(f"File too large ({size:,} bytes). Max {_MAX_PORTRAIT_BYTES:,} bytes.")
            return redirect(url_for('admin.yearly_maps'))

        # ---- Magic-byte check --------------------------------------------
        header = file.stream.read(32)
        file.stream.seek(0)
        detected = _detect_image_type(header)
        if detected is None:
            flash(
                "Uploaded file doesn't look like a real image "
                "(JPEG/PNG/GIF/WEBP signatures didn't match)."
            )
            return redirect(url_for('admin.yearly_maps'))

        # ---- Extension consistency ----------------------------------------
        safe_original = secure_filename(file.filename) or 'upload'
        declared_ext = os.path.splitext(safe_original)[1].lower()
        declared = 'jpg' if declared_ext == '.jpeg' else declared_ext.lstrip('.')
        if declared != detected:
            flash(
                f"File extension {declared_ext!r} doesn't match the actual "
                f"content ({detected!r}). Refusing to save."
            )
            return redirect(url_for('admin.yearly_maps'))

        # ---- Save (server-constructed filename, never user input) ----------
        yearmaps_dir = os.path.join(current_app.static_folder, YEARMAP_DIR)
        os.makedirs(yearmaps_dir, exist_ok=True)
        filename = f'{year}.{detected}'
        path = os.path.join(yearmaps_dir, filename)

        abs_path = os.path.abspath(path)
        abs_dir = os.path.abspath(yearmaps_dir)
        if not abs_path.startswith(abs_dir + os.sep):
            abort(400)

        file.save(path)

        if row is None:
            row = YearMap(year=year, filename=filename)
            db.session.add(row)
            verb = "uploaded"
        else:
            # Replacing: if the previous image had a different extension its
            # file is now stale on disk — remove it so it can't be served.
            if row.filename != filename:
                old_path = os.path.join(yearmaps_dir, row.filename)
                if os.path.abspath(old_path).startswith(abs_dir + os.sep) \
                        and os.path.exists(old_path):
                    os.remove(old_path)
            row.filename = filename
            verb = "replaced"
    else:
        verb = "attribution updated"

    row.source_site = source_site
    row.source_url = source_url
    row.factions = factions
    db.session.commit()

    flash(f"Map for {year} AD {verb}.")
    return redirect(url_for('admin.yearly_maps'))


@admin.route('/yearly-maps/<int:year>/remove', methods=['POST'])
@login_required
@admin_required
def yearly_maps_remove(year):
    """Delete the map image (row + file) for one year."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    row = YearMap.query.filter_by(year=year).first_or_404()

    yearmaps_dir = os.path.join(current_app.static_folder, YEARMAP_DIR)
    path = os.path.join(yearmaps_dir, row.filename)
    if os.path.abspath(path).startswith(os.path.abspath(yearmaps_dir) + os.sep) \
            and os.path.exists(path):
        os.remove(path)

    db.session.delete(row)
    db.session.commit()

    flash(f"Map for {year} AD removed.")
    return redirect(url_for('admin.yearly_maps'))


# ---------------------------------------------------------------------------
# Relationship Types — the two-ended labels for character family ties
# ---------------------------------------------------------------------------

@admin.route('/relationship-types', methods=['GET'])
@login_required
@admin_required
def relationship_types():
    """List relationship types with usage counts. Simpler than the other
    type listings (no search/sort) — the set is small and stable."""
    usage_counts = dict(
        db.session.query(
            Relationship.relationship_type_id,
            func.count(Relationship.id),
        )
        .group_by(Relationship.relationship_type_id)
        .all()
    )
    types = (
        RelationshipType.query
        .filter(RelationshipType.is_hidden.is_(False))
        .order_by(RelationshipType.name)
        .all()
    )
    return render_template(
        'admin/relationship_types.html',
        types=types,
        usage_counts=usage_counts,
        csrf_form=_CsrfOnlyForm(),
    )


@admin.route('/relationship-types/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_relationship_type():
    form = EditRelationshipTypeForm()
    if form.validate_on_submit():
        rel_type = RelationshipType()
        form.populate_obj(rel_type)
        db.session.add(rel_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A relationship type named {rel_type.name!r} already exists.")
            return redirect(url_for('admin.new_relationship_type'))
        flash(f"Created relationship type {rel_type.name!r}.")
        return redirect(url_for('admin.relationship_types'))
    return render_template('admin/relationship_type_edit.html',
                           form=form, relationship_type=None)


@admin.route('/relationship-types/<int:type_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_relationship_type(type_id):
    rel_type = RelationshipType.query.get_or_404(type_id)
    form = EditRelationshipTypeForm(obj=rel_type)
    if form.validate_on_submit():
        form.populate_obj(rel_type)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"A relationship type named {rel_type.name!r} already exists.")
            return redirect(url_for('admin.edit_relationship_type', type_id=rel_type.id))
        flash(f"Updated relationship type {rel_type.name!r}.")
        return redirect(url_for('admin.relationship_types'))
    return render_template('admin/relationship_type_edit.html',
                           form=form, relationship_type=rel_type)


@admin.route('/relationship-types/<int:type_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_relationship_type(type_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    rel_type = RelationshipType.query.get_or_404(type_id)
    name = rel_type.name

    # Refuse while in use — the relationship FK is ON DELETE CASCADE, so
    # deleting a used type would silently erase the ties themselves.
    in_use = Relationship.query.filter_by(relationship_type_id=rel_type.id).count()
    if in_use > 0:
        flash(
            f"Can't delete {name!r}: it's used by {in_use} relationship"
            f"{'' if in_use == 1 else 's'}. Remove those first."
        )
        return redirect(url_for('admin.relationship_types'))

    db.session.delete(rel_type)
    db.session.commit()
    flash(f"Deleted relationship type {name!r}.")
    return redirect(url_for('admin.relationship_types'))


# ---------------------------------------------------------------------------
# API Explorer — try out /api/v1 endpoints from the admin UI
# ---------------------------------------------------------------------------

@admin.route('/api-explorer', methods=['GET'])
@login_required
@admin_required
def api_explorer():
    """Interactive tester for the public JSON API. The endpoint registry
    (single source of truth in app/blueprints/api/registry.py) ships to
    the page as JSON; api_explorer.js builds the param form per endpoint
    and fires same-origin fetch() calls."""
    from app.blueprints.api.registry import ENDPOINTS
    return render_template('admin/api_explorer.html', endpoints=ENDPOINTS)


# ---------------------------------------------------------------------------
# Province Maps — map images per Province location (several allowed, e.g.
# "North part" / "South part") + the placement editor
# ---------------------------------------------------------------------------

from app.models import ProvinceMap, ProvinceMapPlacement
from app.models.province_map import PROVINCEMAP_DIR, POINT_TYPES


@admin.route('/province-maps', methods=['GET'])
@login_required
@admin_required
def province_maps():
    """One block per Province-type Location listing ALL its maps (a
    province may have several, labelled), placement progress per map,
    and add/edit/editor/delete actions."""
    provinces = (
        Location.query
        .join(LocationType, Location.location_type_id == LocationType.id)
        .filter(Location.is_deleted.is_(False),
                LocationType.name == 'Province')
        .order_by(Location.name)
        .all()
    )
    maps_by_loc = {}
    for m in ProvinceMap.query.order_by(ProvinceMap.label,
                                        ProvinceMap.id).all():
        maps_by_loc.setdefault(m.location_id, []).append(m)

    placement_counts = dict(
        db.session.query(ProvinceMapPlacement.province_map_id,
                         func.count(ProvinceMapPlacement.id))
        .group_by(ProvinceMapPlacement.province_map_id)
        .all()
    )
    # Count ALL descendants per province (the editor places the whole
    # subtree, not just direct children). One location load shared by
    # every province's BFS — not one load per province.
    all_rows = (
        db.session.query(Location.id, Location.parent_id)
        .filter(Location.is_deleted.is_(False))
        .all()
    )
    by_parent = {}
    for lid, pid in all_rows:
        by_parent.setdefault(pid, []).append(lid)
    child_counts = {}
    for p in provinces:
        seen = {p.id}
        stack = list(by_parent.get(p.id, []))
        count = 0
        while stack:
            lid = stack.pop()
            if lid in seen:
                continue
            seen.add(lid)
            count += 1
            stack.extend(by_parent.get(lid, []))
        child_counts[p.id] = count

    return render_template(
        'admin/province_maps.html',
        provinces=provinces,
        maps_by_loc=maps_by_loc,
        placement_counts=placement_counts,
        child_counts=child_counts,
        csrf_form=_CsrfOnlyForm(),
    )


def _province_or_404(location_id):
    prov = (
        Location.query
        .join(LocationType, Location.location_type_id == LocationType.id)
        .filter(Location.id == location_id,
                Location.is_deleted.is_(False),
                LocationType.name == 'Province')
        .first()
    )
    if prov is None:
        abort(404)
    return prov


def _province_descendants(province_id):
    """All active locations anywhere UNDER a province in the parent
    hierarchy (commandery -> county -> river...), not just direct
    children. One query + BFS over an in-memory parent map (cheap at
    ~1k locations; cycle-safe). Returns (locations, crumbs) where
    crumbs[id] is the ancestry path INSIDE the province, e.g.
    "Wei Commandery › Ye County"."""
    rows = (
        Location.query
        .filter(Location.is_deleted.is_(False))
        .options(selectinload(Location.location_type))
        .all()
    )
    by_parent = {}
    by_id = {}
    for loc in rows:
        by_id[loc.id] = loc
        by_parent.setdefault(loc.parent_id, []).append(loc)

    def is_commandery(loc):
        return (loc.location_type is not None
                and loc.location_type.name == 'Commandery')

    found = []
    crumbs = {}
    commandery_of = {}   # loc_id -> nearest Commandery ancestor id (or self)
    seen = {province_id}
    queue = [(child, []) for child in by_parent.get(province_id, [])]
    while queue:
        loc, path = queue.pop()
        if loc.id in seen:
            continue
        seen.add(loc.id)
        found.append(loc)
        crumbs[loc.id] = ' › '.join(p.name for p in path)
        if is_commandery(loc):
            commandery_of[loc.id] = loc.id
        else:
            for ancestor in reversed(path):
                if is_commandery(ancestor):
                    commandery_of[loc.id] = ancestor.id
                    break
        queue.extend((child, path + [loc])
                     for child in by_parent.get(loc.id, []))
    found.sort(key=lambda l: l.name)
    return found, crumbs, commandery_of


def _validate_map_upload(file):
    """Shared upload checks. Returns (detected_ext, error_message) —
    exactly one is None."""
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size <= 0:
        return None, "Uploaded file is empty."
    if size > _MAX_PORTRAIT_BYTES:
        return None, (f"File too large ({size:,} bytes). "
                      f"Max {_MAX_PORTRAIT_BYTES:,} bytes.")
    header = file.stream.read(32)
    file.stream.seek(0)
    detected = _detect_image_type(header)
    if detected is None:
        return None, ("Uploaded file doesn't look like a real image "
                      "(JPEG/PNG/GIF/WEBP signatures didn't match).")
    safe_original = secure_filename(file.filename) or 'upload'
    declared_ext = os.path.splitext(safe_original)[1].lower()
    declared = 'jpg' if declared_ext == '.jpeg' else declared_ext.lstrip('.')
    if declared != detected:
        return None, (f"File extension {declared_ext!r} doesn't match the "
                      f"actual content ({detected!r}). Refusing to save.")
    return detected, None


def _map_meta_from_form():
    source_site = (request.form.get('source_site') or '').strip()
    source_url = (request.form.get('source_url') or '').strip()
    label = (request.form.get('label') or '').strip()
    if len(source_site) > 255 or len(source_url) > 2048 or len(label) > 120:
        return None
    return {'source_site': source_site, 'source_url': source_url,
            'label': label}


def _save_map_file(row, file, detected):
    """Write the image as <province_id>_<map_id>.<ext>, removing a
    stale differently-named previous file."""
    maps_dir = os.path.join(current_app.static_folder, PROVINCEMAP_DIR)
    os.makedirs(maps_dir, exist_ok=True)
    filename = f'{row.location_id}_{row.id}.{detected}'
    path = os.path.join(maps_dir, filename)
    abs_dir = os.path.abspath(maps_dir)
    if not os.path.abspath(path).startswith(abs_dir + os.sep):
        abort(400)
    file.save(path)
    if row.filename and row.filename != filename:
        old_path = os.path.join(maps_dir, row.filename)
        if os.path.abspath(old_path).startswith(abs_dir + os.sep) \
                and os.path.exists(old_path):
            os.remove(old_path)
    row.filename = filename


@admin.route('/province-maps/<int:location_id>/create', methods=['POST'])
@login_required
@admin_required
def province_map_create(location_id):
    """Add a NEW map to a province (file required)."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    prov = _province_or_404(location_id)

    meta = _map_meta_from_form()
    if meta is None:
        flash("Label/attribution too long.")
        return redirect(url_for('admin.province_maps'))
    file = request.files.get('image_file')
    if file is None or not file.filename:
        flash("Choose an image file for the new map.")
        return redirect(url_for('admin.province_maps'))
    detected, err = _validate_map_upload(file)
    if err:
        flash(err)
        return redirect(url_for('admin.province_maps'))

    row = ProvinceMap(location_id=prov.id, filename='', **meta)
    db.session.add(row)
    db.session.flush()          # id needed for the filename
    _save_map_file(row, file, detected)
    db.session.commit()
    flash(f"Added map {row.display_label!r} to {prov.name}.")
    return redirect(url_for('admin.province_maps'))


@admin.route('/province-maps/map/<int:map_id>/update', methods=['POST'])
@login_required
@admin_required
def province_map_update(map_id):
    """Update one map: label/attribution always; image only when a new
    file is chosen."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    row = ProvinceMap.query.get_or_404(map_id)

    meta = _map_meta_from_form()
    if meta is None:
        flash("Label/attribution too long.")
        return redirect(url_for('admin.province_maps'))

    file = request.files.get('image_file')
    if file is not None and file.filename:
        detected, err = _validate_map_upload(file)
        if err:
            flash(err)
            return redirect(url_for('admin.province_maps'))
        _save_map_file(row, file, detected)
        verb = "replaced"
    else:
        verb = "updated"

    row.label = meta['label']
    row.source_site = meta['source_site']
    row.source_url = meta['source_url']
    db.session.commit()
    flash(f"Map {row.display_label!r} {verb}.")
    return redirect(url_for('admin.province_maps'))


@admin.route('/province-maps/map/<int:map_id>/delete', methods=['POST'])
@login_required
@admin_required
def province_map_delete(map_id):
    """Delete one map + its file. Placements cascade away with it."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)
    row = ProvinceMap.query.get_or_404(map_id)
    label = row.display_label
    prov_name = row.location.name if row.location else '?'

    maps_dir = os.path.join(current_app.static_folder, PROVINCEMAP_DIR)
    path = os.path.join(maps_dir, row.filename)
    if os.path.abspath(path).startswith(os.path.abspath(maps_dir) + os.sep) \
            and os.path.exists(path):
        os.remove(path)
    db.session.delete(row)
    db.session.commit()
    flash(f"Deleted map {label!r} from {prov_name} (and its placements).")
    return redirect(url_for('admin.province_maps'))


@admin.route('/province-maps/editor/<int:map_id>', methods=['GET'])
@login_required
@admin_required
def province_map_editor(map_id):
    """Interactive placement editor for ONE map of a province."""
    pmap = ProvinceMap.query.get_or_404(map_id)
    prov = pmap.location
    if prov is None or prov.is_deleted:
        abort(404)

    siblings = (
        ProvinceMap.query
        .filter(ProvinceMap.location_id == prov.id)
        .order_by(ProvinceMap.label, ProvinceMap.id)
        .all()
    )
    children, crumbs, commandery_of = _province_descendants(prov.id)
    commanderies = sorted(
        (c for c in children
         if c.location_type and c.location_type.name == 'Commandery'),
        key=lambda c: c.name)
    placements = {
        p.location_id: {'kind': p.kind, 'geometry': p.geometry}
        for p in ProvinceMapPlacement.query.filter_by(
            province_map_id=pmap.id).all()
    }
    payload = {
        'province_id': prov.id,
        'map_id': pmap.id,
        'image_url': url_for('static', filename=pmap.static_path),
        'save_url_template': url_for(
            'admin.province_map_place', map_id=pmap.id, child_id=0),
        'delete_url_template': url_for(
            'admin.province_map_place_delete', map_id=pmap.id, child_id=0),
        'location_edit_url_template': url_for('main.edit_location', id=0),
        'locations': [
            {
                'id': c.id,
                'name': c.name,
                'type_name': (c.location_type.name
                              if c.location_type else ''),
                'icon': ((c.location_type.icon or '')
                         if c.location_type else ''),
                'point_type': (c.location_type.point_type
                               if c.location_type else 'point'),
            }
            for c in children
        ],
        'placements': placements,
    }
    return render_template(
        'admin/province_map_editor.html',
        province=prov,
        pmap=pmap,
        siblings=siblings,
        children=children,
        crumbs=crumbs,
        commandery_of=commandery_of,
        commanderies=commanderies,
        payload=payload,
        csrf_form=_CsrfOnlyForm(),
    )


def _validate_geometry(kind, geometry):
    """Shape-check placement geometry (image-pixel coords)."""
    def is_pair(v):
        return (isinstance(v, (list, tuple)) and len(v) == 2
                and all(isinstance(n, (int, float)) for n in v))
    if kind == 'point':
        return is_pair(geometry)
    if kind == 'line':
        return (isinstance(geometry, list) and len(geometry) >= 2
                and all(is_pair(p) for p in geometry))
    if kind == 'region':
        return (isinstance(geometry, list) and len(geometry) >= 3
                and all(is_pair(p) for p in geometry))
    return False


@admin.route('/province-maps/map/<int:map_id>/placements/<int:child_id>',
             methods=['POST'])
@login_required
@admin_required
def province_map_place(map_id, child_id):
    """Create or replace one child location's placement on one map.
    JSON body: {kind, geometry}, kind matching the child type's
    point_type."""
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        return jsonify(error='Bad CSRF token.'), 400
    pmap = ProvinceMap.query.get_or_404(map_id)
    child = Location.query.get_or_404(child_id)
    descendants, _, _ = _province_descendants(pmap.location_id)
    if child.is_deleted or child.id not in {d.id for d in descendants}:
        return jsonify(error='Location is not a descendant of this '
                             'province.'), 400

    data = request.get_json(silent=True) or {}
    kind = data.get('kind')
    geometry = data.get('geometry')
    if kind not in POINT_TYPES:
        return jsonify(error=f'Bad kind {kind!r}.'), 400
    expected = (child.location_type.point_type
                if child.location_type else 'point')
    if kind != expected:
        return jsonify(error=f'Kind {kind!r} does not match the location '
                             f"type's placement type {expected!r}."), 400
    if not _validate_geometry(kind, geometry):
        return jsonify(error='Geometry shape invalid for this kind.'), 400

    placement = ProvinceMapPlacement.query.filter_by(
        province_map_id=pmap.id, location_id=child.id).first()
    created = placement is None
    if created:
        placement = ProvinceMapPlacement(province_map_id=pmap.id,
                                         location_id=child.id,
                                         kind=kind, geometry=geometry)
        db.session.add(placement)
    else:
        placement.kind = kind
        placement.geometry = geometry
    db.session.commit()
    return jsonify(ok=True, created=created, location_id=child.id,
                   kind=kind)


@admin.route('/province-maps/map/<int:map_id>/placements/<int:child_id>/delete',
             methods=['POST'])
@login_required
@admin_required
def province_map_place_delete(map_id, child_id):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        return jsonify(error='Bad CSRF token.'), 400
    pmap = ProvinceMap.query.get_or_404(map_id)
    placement = ProvinceMapPlacement.query.filter_by(
        province_map_id=pmap.id, location_id=child_id).first()
    if placement is None:
        return jsonify(error='No placement for that location.'), 404
    db.session.delete(placement)
    db.session.commit()
    return jsonify(ok=True, location_id=child_id)
