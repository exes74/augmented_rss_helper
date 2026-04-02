"""
Point d'entrée principal de l'application RSS Veille.
"""
import os
import logging
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail

from config import config

# ─── Extensions globales ──────────────────────────────────────────────────
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()


def _run_incremental_migrations(app: Flask) -> None:
    """
    Applique les migrations incrémentales (colonnes ajoutées après la création
    initiale des tables). Utilise ALTER TABLE ... ADD COLUMN IF NOT EXISTS pour
    être idempotent — sans risque de casser une base existante.
    """
    migrations = [
        # v2 : enrichissement full-text via newspaper3k
        "ALTER TABLE articles ADD COLUMN IF NOT EXISTS enriched BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE INDEX IF NOT EXISTS ix_articles_enriched ON articles (enriched)",
        # v3 : author en TEXT pour supporter les longues listes d'auteurs (ex: arXiv)
        "ALTER TABLE articles ALTER COLUMN author TYPE TEXT",
        # v4 : table de configuration des prompts LLM
        """
        CREATE TABLE IF NOT EXISTS prompt_configs (
            id SERIAL PRIMARY KEY,
            prompt_key VARCHAR(64) NOT NULL UNIQUE,
            content TEXT NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_by VARCHAR(255)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_prompt_configs_prompt_key ON prompt_configs (prompt_key)",
    ]

    try:
        with db.engine.connect() as conn:
            for sql in migrations:
                try:
                    conn.execute(db.text(sql))
                    conn.commit()
                except Exception as e:
                    app.logger.debug(f"Migration ignorée (déjà appliquée ?) : {e}")
        app.logger.info("Migrations incrémentales appliquées.")
    except Exception as e:
        app.logger.warning(f"Erreur lors des migrations incrémentales : {e}")


def create_app(config_name: str = None) -> Flask:
    """Factory de création de l'application Flask."""
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "production")
        if config_name == "development":
            config_name = "development"
        else:
            config_name = "production"

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # ─── Initialisation des extensions ────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)

    # ─── Configuration Flask-Login ─────────────────────────────────────────
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
    login_manager.login_message_category = "warning"

    # ─── Logging ──────────────────────────────────────────────────────────
    setup_logging(app)

    # ─── Enregistrement des blueprints ────────────────────────────────────
    register_blueprints(app)

    # ─── Création des tables (si nécessaire) ──────────────────────────────
    with app.app_context():
        try:
            # Ne crée que les tables qui n'existent pas encore
            db.metadata.create_all(
                bind=db.engine,
                checkfirst=True
            )
        except Exception as e:
            app.logger.warning(f"Init DB ignorée (tables déjà existantes): {e}")

        # Migrations incrémentales : colonnes ajoutées après la création initiale
        _run_incremental_migrations(app)

    # ─── Filtre Jinja2 : Markdown → HTML ─────────────────────────────────────
    def _md_to_html(text: str) -> str:
        """Convertit du Markdown en HTML pour l'affichage dans les templates."""
        if not text:
            return ""
        try:
            import markdown as md_lib
            from markupsafe import Markup
            result = md_lib.markdown(
                text,
                extensions=["nl2br", "sane_lists", "tables"]
            )
            return Markup(result)
        except ImportError:
            # Fallback si markdown n'est pas installé
            import re
            from markupsafe import Markup, escape
            text = str(escape(text))
            text = re.sub(r'^#{1,3}\s+(.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
            text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
            text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
            text = re.sub(r'^[\u2022\-\*]\s+(.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
            text = re.sub(r'(<li>.*</li>)', r'<ul>\1</ul>', text, flags=re.DOTALL)
            text = text.replace('\n', '<br>')
            return Markup(text)

    app.jinja_env.filters['markdown'] = _md_to_html

    # ─── Filtre Jinja2 : JSON string → Python list ───────────────────────
    import json as _json
    def _fromjson(value):
        if not value:
            return []
        try:
            return _json.loads(value)
        except Exception:
            return []
    app.jinja_env.filters['fromjson'] = _fromjson

    # ─── Route racine ─────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return redirect(url_for("dashboard.index"))

    return app


def register_blueprints(app: Flask) -> None:
    """Enregistre tous les blueprints de l'application."""
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.feeds import feeds_bp
    from routes.categories import categories_bp
    from routes.syntheses import syntheses_bp
    from routes.settings import settings_bp
    from routes.admin import admin_bp
    from routes.admin_tasks import admin_tasks_bp
    from routes.admin_prompts import admin_prompts_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(feeds_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(syntheses_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(admin_tasks_bp)
    app.register_blueprint(admin_prompts_bp)


def setup_logging(app: Flask) -> None:
    """Configure le logging structuré."""
    import os
    log_dir = app.config.get("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"))

    # Handler fichier
    file_handler = logging.FileHandler(os.path.join(log_dir, "app.log"))
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(log_level)

    # Logger racine
    logging.basicConfig(level=log_level, handlers=[file_handler, console_handler])


# ─── User loader pour Flask-Login ─────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    from models.user import User
    return User.query.get(int(user_id))


# ─── Point d'entrée ───────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
