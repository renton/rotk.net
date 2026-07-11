import os
import secrets
from flask import Flask, g
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


def _build_csp(nonce):
    """CSP header for every response. Other security headers (HSTS,
    X-Content-Type-Options, Referrer-Policy) and HTTP→HTTPS redirects come
    from Caddy in stateful_boilerplate, so we don't duplicate them here.
    frame-ancestors 'none' replaces what X-Frame-Options used to do.

    Google Analytics endpoints:
      - googletagmanager.com  — script + (sometimes) image pixels
      - google-analytics.com  — hit-collection (fetch / XHR)
      - analytics.google.com  — measurement protocol

    The inline gtag init block is allowed via the per-request nonce only
    (no 'unsafe-inline')."""
    return (
        "default-src 'self'; "
        "img-src 'self' https://cdn.jsdelivr.net "
            "https://www.google-analytics.com https://www.googletagmanager.com "
            # ESRI ArcGIS Online tile services for the /map view —
            # World_Terrain_Base gives shaded relief + water with no
            # roads / labels, which keeps the modern Chinese road
            # network and place names from cluttering a Three Kingdoms
            # era map. Served from server.arcgisonline.com.
            "https://server.arcgisonline.com "
            "https://services.arcgisonline.com "
            "data:; "
        f"script-src 'self' https://cdn.jsdelivr.net "
            f"https://www.googletagmanager.com 'nonce-{nonce}'; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        # Font Awesome ships its WOFF2/TTF font files alongside the CSS on
        # jsdelivr; without this they'd fall back to default-src 'self' and
        # be blocked.
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self' "
            "https://*.google-analytics.com https://*.analytics.google.com "
            "https://*.googletagmanager.com "
            # Bootstrap's CSS/JS reference source maps; browsers fetch them
            # as XHR (connect-src, not script/style-src) when dev tools is
            # open. Allowed so the console stays clean during debugging.
            "https://cdn.jsdelivr.net; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


def create_app(config_name):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    @app.before_request
    def _generate_csp_nonce():
        # Cryptographically random per request so it's not predictable.
        # url-safe so it slots straight into the header without escaping.
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        # Exposes `csp_nonce` in every template — the GA inline script in
        # base.html sets nonce="{{ csp_nonce }}" so CSP will trust it.
        return {'csp_nonce': getattr(g, 'csp_nonce', '')}

    @app.after_request
    def _set_csp(response):
        nonce = getattr(g, 'csp_nonce', '')
        response.headers.setdefault("Content-Security-Policy", _build_csp(nonce))
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

    # Public read-only JSON API. Whole-blueprint rate limit — generous
    # enough for an MCP client, tight enough to blunt scraping.
    from app.blueprints.api import api as api_blueprint
    limiter.limit("120/minute")(api_blueprint)
    app.register_blueprint(api_blueprint, url_prefix='/api/v1')

    # Importing edit_log registers SQLAlchemy Mapper event listeners that
    # write to the Edit audit table on every ORM insert/update/delete.
    # Side-effect-only import; nothing in here is called by name.
    from app import edit_log  # noqa: F401

    return app
