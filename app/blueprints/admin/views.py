from flask import render_template, redirect, url_for, flash, current_app, abort, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import SubmitField

from app import db
from app.models import User, Chapter, Character
from tools.decorators import admin_required
from tools.book_parser import find_character_mentions
from . import admin


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
