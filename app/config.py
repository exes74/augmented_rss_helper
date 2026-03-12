"""
Configuration de l'application RSS Veille.
Toutes les valeurs sensibles sont lues depuis les variables d'environnement.
"""
import os
from datetime import timedelta


class Config:
    """Configuration de base."""

    # ─── Sécurité ─────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # ─── Base de données ──────────────────────────────────────────────────
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql://rssuser:changeme@localhost:5432/rssveille"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }

    # ─── Redis / Celery ───────────────────────────────────────────────────
    REDIS_URL = os.environ.get("REDIS_URL", "redis://:redispass@localhost:6379/0")
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TIMEZONE = os.environ.get("TIMEZONE", "Europe/Paris")
    CELERY_ENABLE_UTC = True

    # ─── Sessions / Auth ──────────────────────────────────────────────────
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True

    # ─── Email ────────────────────────────────────────────────────────────
    MAIL_SERVER = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("SMTP_PORT", 587))
    MAIL_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
    MAIL_USE_SSL = os.environ.get("SMTP_USE_SSL", "false").lower() == "true"
    MAIL_USERNAME = os.environ.get("SMTP_USER", "")
    MAIL_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_FROM", "noreply@rssveille.local")
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
    EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "smtp")  # smtp | sendgrid

    # ─── OpenAI / LLM ────────────────────────────────────────────────────
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")  # openai | ollama
    LLM_MAX_TOKENS_DAILY = int(os.environ.get("LLM_MAX_TOKENS_DAILY", 50000))
    LLM_MAX_TOKENS_WEEKLY = int(os.environ.get("LLM_MAX_TOKENS_WEEKLY", 100000))

    # ─── Planification ────────────────────────────────────────────────────
    RSS_FETCH_HOUR = int(os.environ.get("RSS_FETCH_HOUR", 6))
    RSS_FETCH_MINUTE = int(os.environ.get("RSS_FETCH_MINUTE", 0))
    DAILY_SYNTHESIS_HOUR = int(os.environ.get("DAILY_SYNTHESIS_HOUR", 7))
    DAILY_SYNTHESIS_MINUTE = int(os.environ.get("DAILY_SYNTHESIS_MINUTE", 0))
    WEEKLY_SYNTHESIS_DAY = os.environ.get("WEEKLY_SYNTHESIS_DAY", "monday")
    WEEKLY_SYNTHESIS_HOUR = int(os.environ.get("WEEKLY_SYNTHESIS_HOUR", 8))
    TIMEZONE = os.environ.get("TIMEZONE", "Europe/Paris")

    # ─── Application ──────────────────────────────────────────────────────
    APP_NAME = "RSS Veille"
    APP_URL = os.environ.get("APP_URL", "http://localhost")
    MAX_FEEDS_PER_USER = int(os.environ.get("MAX_FEEDS_PER_USER", 100))
    MAX_CATEGORIES_PER_USER = int(os.environ.get("MAX_CATEGORIES_PER_USER", 20))
    FEED_ERROR_THRESHOLD = 3  # Nombre d'erreurs consécutives avant marquage "mort"
    ARTICLES_RETENTION_DAYS = int(os.environ.get("ARTICLES_RETENTION_DAYS", 90))

    # ─── Logging ──────────────────────────────────────────────────────────
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")


class DevelopmentConfig(Config):
    """Configuration pour le développement."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SQLALCHEMY_ECHO = False


class ProductionConfig(Config):
    """Configuration pour la production."""
    DEBUG = False
    TESTING = False


class TestingConfig(Config):
    """Configuration pour les tests."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
