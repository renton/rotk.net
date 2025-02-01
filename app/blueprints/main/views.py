import re
from flask import render_template, abort, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models import Chapter, Character, Faction, Role
from . import main

@main.route('/', methods=['GET'])
def index():
    chapters = Chapter.query.all()

    return render_template(
        'table_of_contents.html',
        chapters=chapters
    )

@main.route('/chapter/<int:chapter_num>', methods=['GET'])
def chapter(chapter_num):

    chapter = Chapter.query.filter(Chapter.chapter_num == chapter_num).first()

    print(chapter)
    if not chapter:
        abort(404)

    return render_template(
        'chapter.html',
        chapter=chapter,
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
        'characters.html',
        characters=characters,
        pagination=pagination,
        page=page
    )

@main.route('/factions', methods=['GET'])
def factions():

    factions = Faction.query.order_by(Faction.name).all()

    return render_template(
        'factions.html',
        factions=factions
    )

@main.route('/roles', methods=['GET'])
def roles():

    roles = Role.query.order_by(Role.name).all()

    return render_template(
        'roles.html',
        roles=roles
    )
