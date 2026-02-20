import os
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from flask_babel import Babel

db = SQLAlchemy()

def create_app():
    load_dotenv()

    app = Flask(__name__)

    # -------- Babel setup --------
    babel = Babel()

    def get_locale():
        # 1) Use saved language (cookie) if set
        lang = request.cookies.get("lang")
        if lang:
            return lang

        # 2) Otherwise use browser language
        return request.accept_languages.best_match([
            "en", "es", "fr", "de", "it", "pt", "nl",
            "ar", "hi", "ur", "ja", "ko", "sw",
            "yo", "ig", "zh"
        ]) or "en"

    babel.init_app(app, locale_selector=get_locale)
    # -------- End Babel setup --------

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    db_url = os.getenv("DATABASE_URL", "sqlite:///lighterlock.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        from .models import Lighter
        db.create_all()

    return app
