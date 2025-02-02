import re
from flask import render_template, abort, request, current_app, flash, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import Chapter, Character, Faction, Role
from . import main
from .forms import EditCharacterForm, EditFactionForm, EditRoleForm

from tools.decorators import admin_required
from tools.book_parser import get_characters_for_chapter, build_needle_pattern, build_name_ref_html

@main.route('/', methods=['GET'])
def index():
    chapters = Chapter.query.all()

    return render_template(
        'book/table_of_contents.html',
        chapters=chapters
    )

@main.route('/chapter/<int:chapter_num>', methods=['GET'])
def chapter(chapter_num):

    with db.session.no_autoflush:
        chapter = Chapter.query.filter(Chapter.chapter_num == chapter_num).first()

        if not chapter:
            abort(404)

        # TODO sort alphabetically
        characters = get_characters_for_chapter(chapter.id)
        characters.sort(key=lambda x: x.name)

        replacements = {}

        for character in characters:
            for name_needle in character.get_all_name_labels():            
                replacements[name_needle] = build_name_ref_html(character)
        # Create a regex pattern that matches any of the needles
        pattern = build_needle_pattern(list(replacements.keys()))

        # Function to replace the found needle with the replacement
        def replace_match(match):
            return replacements[match.group(0)]

        # Perform the find-and-replace in a single pass
        modified_text = pattern.sub(replace_match, chapter.content)

        chapter.content = modified_text

        return render_template(
            'book/chapter.html',
            chapter=chapter,
            characters=characters,
        )

@main.route('/characters', methods=['GET'])
def characters():

    page = request.args.get('page', 1, type=int)

    pagination = Character.query.order_by(Character.name).paginate(
        page=page,
        per_page=current_app.config['CHARACTERS_PER_PAGE'],
        error_out=False
    )

    characters = pagination.items

    return render_template(
        'characters/characters.html',
        characters=characters,
        pagination=pagination,
        page=page
    )

@main.route('/characters/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_character(id):
    character = Character.query.get_or_404(id)
    form = EditCharacterForm(obj=character)

    if form.validate_on_submit():
        form.populate_obj(character)

        db.session.add(character)
        db.session.commit()
        flash('The character has been updated.')
        return redirect(url_for("main.edit_character", id=character.id))

    return render_template(
        'characters/character_edit.html',
        form=form
    )

@main.route('/factions', methods=['GET'])
def factions():

    factions = Faction.query.order_by(Faction.name).all()

    return render_template(
        'factions/factions.html',
        factions=factions
    )

@main.route('/factions/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_faction(id):
    faction = Faction.query.get_or_404(id)
    form = EditFactionForm(obj=faction)

    if form.validate_on_submit():
        form.populate_obj(faction)

        db.session.add(faction)
        db.session.commit()
        flash('The faction has been updated.')
        return redirect(url_for("main.factions", id=faction.id))

    return render_template(
        'factions/faction_edit.html',
        form=form
    )

@main.route('/roles', methods=['GET'])
def roles():

    roles = Role.query.order_by(Role.name).all()

    return render_template(
        'roles/roles.html',
        roles=roles
    )

@main.route('/roles/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_role(id):
    role = Role.query.get_or_404(id)
    form = EditRoleForm(obj=role)

    if form.validate_on_submit():
        form.populate_obj(role)

        db.session.add(role)
        db.session.commit()
        flash('The role has been updated.')
        return redirect(url_for("main.roles", id=role.id))

    return render_template(
        'roles/role_edit.html',
        form=form
    )
