from flask import Flask, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_talisman import Talisman
from flask_bootstrap import Bootstrap5

# from flask_mail import Mail
# from flask_moment import Moment

# from flask_login import LoginManager
# from flask_pagedown import PageDown
from config import config

bootstrap = Bootstrap5()
# mail = Mail()
# moment = Moment()
db = SQLAlchemy()
# pagedown = PageDown()

# login_manager = LoginManager()
# login_manager.login_view = 'auth.login'

def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    # Define custom CSP
    csp = {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://cdn.jsdelivr.net"],
        "style-src": ["'self'", "https://cdn.jsdelivr.net"],
    }
    # Apply Talisman with the custom CSP

    Talisman(app, content_security_policy=csp, force_https=True)

    bootstrap.init_app(app)
    #mail.init_app(app)
    #moment.init_app(app)
    db.init_app(app)
    #login_manager.init_app(app)
    #pagedown.init_app(app)

    #if app.config['SSL_REDIRECT']:
    #    from flask_sslify import SSLify
    #    sslify = SSLify(app)

    from app.blueprints.main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    #from .auth import auth as auth_blueprint
    #app.register_blueprint(auth_blueprint, url_prefix='/auth')

    #from .api import api as api_blueprint
    #app.register_blueprint(api_blueprint, url_prefix='/api/v1')

    return app