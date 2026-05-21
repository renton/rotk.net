import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bootstrap import Bootstrap5
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_login import LoginManager
from tools.dbm import DbManager

from config import config

bootstrap = Bootstrap5()
db = SQLAlchemy()
dbm = DbManager(db)
mail = Mail()

login_manager = LoginManager()
login_manager.login_view = 'auth.login'

limiter = Limiter(key_func=get_remote_address, default_limits=[])


# CSP for every response. Other security headers (HSTS, X-Content-Type-Options,
# Referrer-Policy) and HTTP→HTTPS redirects are added by the front-edge Caddy
# from stateful_boilerplate, so we don't duplicate them here. frame-ancestors
# 'none' covers what X-Frame-Options used to do.
_CSP = (
    "default-src 'self'; "
    "img-src 'self' https://cdn.jsdelivr.net data:; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    @app.after_request
    def _set_csp(response):
        response.headers.setdefault("Content-Security-Policy", _CSP)
        return response

    bootstrap.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    from app.blueprints.main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    from app.blueprints.auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint, url_prefix='/auth')

    from app.blueprints.admin import admin as admin_blueprint
    app.register_blueprint(admin_blueprint, url_prefix='/admin')

    return app
