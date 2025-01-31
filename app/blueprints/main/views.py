import re
from flask import render_template, abort
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

    title = re.sub(";", ";<br>", chapter.title)

    return render_template(
        'chapter.html',
        title=title,
        chapter=chapter,
    )

@main.route('/characters', methods=['GET'])
def characters():

    characters = Character.query.all()

    return render_template(
        'characters.html',
        characters=characters
    )

@main.route('/factions', methods=['GET'])
def factions():

    factions = Faction.query.all()

    return render_template(
        'factions.html',
        factions=factions
    )

@main.route('/roles', methods=['GET'])
def roles():

    roles = Role.query.all()

    return render_template(
        'roles.html',
        roles=roles
    )