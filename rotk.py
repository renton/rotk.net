import os, sys

# Load .env if present, but never override values that are already in the
# environment. In docker-compose deployments the compose `environment:`
# block is the source of truth; a baked-in .env (or a stale .env in a
# bind-mount) must not silently replace what compose set.
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=False)

import click
from sqlalchemy.exc import IntegrityError
from app import create_app, db
from tools.scraper import scrape_rotk_book, scrape_rotk_characters
from tools.book_parser import get_characters_for_chapter, scan_chapter_for_characters
from flask import render_template, request, jsonify

# COV = None
# if os.environ.get('FLASK_COVERAGE'):
#     import coverage
#     COV = coverage.coverage(branch=True, include='app/*')
#     COV.start()

# from flask_migrate import Migrate, upgrade
from app.models import \
    Chapter, Character, Faction, Role, User

app = create_app(os.getenv('FLASK_ENV') or 'default')

# migrate = Migrate(app, db)

@app.cli.command()
def build_chapter_character_association():
    """Populate the chapter_character table by regex-scanning every chapter
    for every character's names/aliases. Idempotent — clears existing rows
    for each chapter before refilling so reruns reflect current data."""
    chapters = Chapter.query.order_by(Chapter.chapter_num).all()
    total = 0
    for chapter in chapters:
        chapter.characters = scan_chapter_for_characters(chapter)
        total += len(chapter.characters)
        print(f"chapter {chapter.chapter_num}: {len(chapter.characters)} characters")
        db.session.commit()
    print(f"\nDone. {total} character/chapter rows.")


@app.cli.command()
def scrape_book():
    chapters = scrape_rotk_book()

    for i, content in enumerate(chapters):
        title = content[0]
        copy = content[1]
        try:
            chapter = Chapter(
                name=title,
                chapter_num=i+1,
                content=copy,
            )        
            db.session.add(chapter)
            db.session.commit()
        except Exception as e:
            print(e)
            db.session.rollback()

@app.cli.command()
def scrape_characters():
    characters, factions, roles = scrape_rotk_characters()

    # add factions
    for i, faction in enumerate(factions):
        try:
            new_faction = Faction(
                name=faction
            )
            db.session.add(new_faction)    
            db.session.commit()
        except Exception as e:
            print(f"Duplicate key error for faction {faction}")
            db.session.rollback()

    # add roles
    for role in roles:
        try:
            new_role = Role(
                name=role
            )
            db.session.add(new_role)
            db.session.commit()

        except IntegrityError as e:
            print(f"Duplicate key error for role {role}")
            db.session.rollback()

    # get faction index
    faction_index = {faction.name: faction for faction in Faction.query.all()}

    # get role index
    role_index = {role.name: role for role in Role.query.all()}

    bad_eggs = []
    # add characters
    for character in characters:
        try:
            latest_faction_name = character.pop('latest_faction', None)
            latest_faction_obj = faction_index.get(latest_faction_name) if latest_faction_name else None

            faction_objs = [faction_index[f] for f in character['factions'] if f in faction_index]
            role_objs = [role_index[r] for r in character['roles'] if r in role_index]

            character['factions'] = faction_objs
            character['roles'] = role_objs

            new_character = Character(**character)
            new_character.set_current_faction(latest_faction_obj)
            db.session.add(new_character)

            db.session.commit()
        except Exception as e:
            print(e)
            bad_eggs.append((e, character))
            db.session.rollback()

    print("\n==========")
    for egg in bad_eggs:
        print(egg)

@app.cli.command()
def create_all():
    db.create_all()


@app.cli.command()
@click.argument('email')
def make_admin(email):
    """Promote the user with the given email to administrator (and mark
    them confirmed). Useful for bootstrapping the first admin."""
    user = User.query.filter_by(email=email.lower()).first()
    if user is None:
        print(f"No user with email {email!r}.")
        sys.exit(1)
    user.is_administrator = True
    user.confirmed = True
    db.session.add(user)
    db.session.commit()
    print(f"Promoted {user.username} ({user.email}) to admin.")


@app.cli.command()
@click.argument('email')
@click.argument('username')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True,
              help='Password for the new user (prompted if not provided).')
@click.option('--admin/--no-admin', default=False, help='Mark the user as administrator.')
def create_user(email, username, password, admin):
    """Create a new user (mainly for bootstrapping the first admin)."""
    if User.query.filter_by(email=email.lower()).first():
        print(f"Email {email!r} is already registered.")
        sys.exit(1)
    if User.query.filter_by(username=username).first():
        print(f"Username {username!r} is already in use.")
        sys.exit(1)

    user = User(
        email=email.lower(),
        username=username,
        confirmed=True,
        is_administrator=admin,
    )
    user.password = password
    db.session.add(user)
    db.session.commit()
    print(f"Created {user.username} ({user.email})" + (" [admin]" if admin else "") + ".")

@app.cli.command()
def deploy():
    """Run deployment tasks."""
    pass
    # migrate database to latest revision
    #upgrade()

    # create or update user roles
    #Role.insert_roles()

    # ensure all users are following themselves
    #User.add_self_follows()

# @app.shell_context_processor
# def make_shell_context():
#     return dict(db=db, User=User, Follow=Follow, Role=Role,
#                 Permission=Permission, Post=Post, Comment=Comment)


# @app.cli.command()
# @click.option('--coverage/--no-coverage', default=False,
#               help='Run tests under code coverage.')
# @click.argument('test_names', nargs=-1)
# def test(coverage, test_names):
#     """Run the unit tests."""
#     if coverage and not os.environ.get('FLASK_COVERAGE'):
#         import subprocess
#         os.environ['FLASK_COVERAGE'] = '1'
#         sys.exit(subprocess.call(sys.argv))

#     import unittest
#     if test_names:
#         tests = unittest.TestLoader().loadTestsFromNames(test_names)
#     else:
#         tests = unittest.TestLoader().discover('tests')
#     unittest.TextTestRunner(verbosity=2).run(tests)
#     if COV:
#         COV.stop()
#         COV.save()
#         print('Coverage Summary:')
#         COV.report()
#         basedir = os.path.abspath(os.path.dirname(__file__))
#         covdir = os.path.join(basedir, 'tmp/coverage')
#         COV.html_report(directory=covdir)
#         print('HTML version: file://%s/index.html' % covdir)
#         COV.erase()


# @app.cli.command()
# @click.option('--length', default=25,
#               help='Number of functions to include in the profiler report.')
# @click.option('--profile-dir', default=None,
#               help='Directory where profiler data files are saved.')
# def profile(length, profile_dir):
#     """Start the application under the code profiler."""
#     from werkzeug.contrib.profiler import ProfilerMiddleware
#     app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[length],
#                                       profile_dir=profile_dir)
#     app.run()


@app.errorhandler(403)
def forbidden(e):
    if request.accept_mimetypes.accept_json and \
            not request.accept_mimetypes.accept_html:
        response = jsonify({'error': 'forbidden'})
        response.status_code = 403
        return response
    return render_template('errors/403.html'), 403


@app.errorhandler(404)
def page_not_found(e):
    if request.accept_mimetypes.accept_json and \
            not request.accept_mimetypes.accept_html:
        response = jsonify({'error': 'not found'})
        response.status_code = 404
        return response
    return render_template('errors/404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    if request.accept_mimetypes.accept_json and \
            not request.accept_mimetypes.accept_html:
        response = jsonify({'error': 'internal server error'})
        response.status_code = 500
        return response
    return render_template('errors/500.html'), 500
