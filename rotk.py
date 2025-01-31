import os, sys

# load .env file
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=True)

import click
from sqlalchemy.exc import IntegrityError
from app import create_app, db
from tools.scraper import scrape_rotk_book, scrape_rotk_characters
from flask import render_template, request, jsonify, Response

# COV = None
# if os.environ.get('FLASK_COVERAGE'):
#     import coverage
#     COV = coverage.coverage(branch=True, include='app/*')
#     COV.start()

# from flask_migrate import Migrate, upgrade
from app.models import \
    Chapter, Character, Faction, Role

app = create_app(os.getenv('FLASK_ENV') or 'default')

# migrate = Migrate(app, db)

@app.after_request
def set_csp_header(response: Response):
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.jsdelivr.net;"
    )
    return response

# TODO build the model in the scraper
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

    # add characters
    for character in characters:
        try:
            faction_objs = []
            for faction in character['factions']:
                if faction in faction_index:
                    faction_objs.append(faction_index[faction])


            role_objs = []
            for role in character['roles']:
                if role in role_index:
                    role_objs.append(role_index[role])

            character['factions'] = faction_objs
            character['roles'] = role_objs

            print(character)

            new_character = Character(
                **character
            )
            db.session.add(new_character)

            db.session.commit()
        except Exception as e:
            print(e)
            db.session.rollback()

@app.cli.command()
def create_all():
    db.create_all()

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
