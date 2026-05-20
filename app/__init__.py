import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_talisman import Talisman
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


def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    csp = {
        "default-src": ["'self'"],
        "img-src": ["'self'", "https://cdn.jsdelivr.net", "http://www.w3.org", "data:"],
        "script-src": ["'self'", "https://cdn.jsdelivr.net"],
        "style-src": ["'self'", "https://cdn.jsdelivr.net", "'unsafe-inline'"],
    }
    Talisman(app, content_security_policy=csp, force_https=True)

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
