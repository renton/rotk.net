import re
from flask import render_template, abort
from app.models import Chapter
from . import main

@main.route('/', methods=['GET', 'POST'])
def index():
    chapters = Chapter.query.all()

    return render_template(
        'table_of_contents.html',
        chapters=chapters
    )

@main.route('/chapter/<int:chapter_num>', methods=['GET', 'POST'])
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