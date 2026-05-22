import os

from flask import render_template, redirect, url_for, flash, current_app, abort, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import SubmitField

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import db
from app.models import User, Chapter, Character, Tag, TagAssociation
from app.models.character import Portrait, PORTRAIT_DIR
from tools.decorators import admin_required
from tools.book_parser import find_character_mentions
from .forms import EditTagForm
from . import admin


PORTRAIT_TARGET_TYPE = 'portrait'   # TagAssociation.target_type for Portrait rows.


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
    addable_characters = []

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
                'faction': character.latest_faction,
            })
            if character.latest_faction is not None:
                seen_factions[character.latest_faction.id] = character.latest_faction
        faction_options = sorted(seen_factions.values(), key=lambda f: f.name)

        associated_ids = {c.id for c in associated}
        addable_query = Character.query.order_by(Character.name)
        if associated_ids:
            addable_query = addable_query.filter(~Character.id.in_(associated_ids))
        addable_characters = addable_query.all()

    return render_template(
        'admin/chapter_associations.html',
        chapters=chapters,
        selected=selected,
        rows=rows,
        faction_options=faction_options,
        addable_characters=addable_characters,
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


@admin.route('/chapter-associations/<int:chapter_num>/add', methods=['POST'])
@login_required
@admin_required
def chapter_associations_add(chapter_num):
    form = _CsrfOnlyForm()
    if not form.validate_on_submit():
        abort(400)

    chapter = Chapter.query.filter_by(chapter_num=chapter_num).first_or_404()

    raw_id = (request.form.get('character_id') or '').strip()
    raw_name = (request.form.get('character_name') or '').strip()

    character = None
    if raw_id.isdigit():
        character = Character.query.get(int(raw_id))
    elif raw_name:
        matches = Character.query.filter(Character.name == raw_name).all()
        if len(matches) == 1:
            character = matches[0]
        elif len(matches) > 1:
            flash(
                f"Multiple characters named {raw_name!r}. "
                f"Use the picker (it sends the character ID) instead of typing the name."
            )
            return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    if character is None:
        flash("Couldn't find a character matching that selection.")
        return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))

    if character in chapter.characters:
        flash(f"{character.name} is already associated with chapter {chapter.chapter_num}.")
    else:
        chapter.characters.append(character)
        db.session.commit()
        flash(f"Added {character.name} to chapter {chapter.chapter_num}.")

    return redirect(url_for('admin.chapter_associations', chapter_num=chapter_num))


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

    if search:
        like = f"%{search}%"
        query = query.filter(or_(
            Character.name.ilike(like),
            Portrait.description.ilike(like),
        ))

    if source_site:
        query = query.filter(Portrait.source_site == source_site)

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

    return render_template(
        'admin/image_manager.html',
        pagination=pagination,
        source_sites=source_sites,
        all_tags=all_tags,
        search=search,
        source_site=source_site,
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


# ----- Tag manager ---------------------------------------------------------

_TAG_SORTS = ('name', 'created_at')
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

    query = Tag.query
    if search:
        query = query.filter(Tag.name.ilike(f"%{search}%"))

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
    db.session.delete(tag)   # cascade removes TagAssociation rows
    db.session.commit()
    flash(f"Deleted tag {name!r}.")
    return redirect(url_for('admin.tags'))
