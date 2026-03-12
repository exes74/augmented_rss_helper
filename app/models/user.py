"""
Modèle utilisateur.
"""
import json
from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from main import db


class User(UserMixin, db.Model):
    """Modèle représentant un utilisateur de l'application."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")  # admin | user
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    invited_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Préférences stockées en JSON
    _preferences = db.Column("preferences_json", db.Text, nullable=True)

    # ─── Relations ────────────────────────────────────────────────────────
    categories = db.relationship("Category", backref="owner", lazy="dynamic",
                                  cascade="all, delete-orphan")
    feeds = db.relationship("Feed", backref="owner", lazy="dynamic",
                             cascade="all, delete-orphan")
    syntheses = db.relationship("Synthesis", backref="owner", lazy="dynamic",
                                 cascade="all, delete-orphan")
    subscriptions_owned = db.relationship(
        "Subscription", foreign_keys="Subscription.owner_user_id",
        backref="owner", lazy="dynamic", cascade="all, delete-orphan"
    )

    # ─── Propriétés ───────────────────────────────────────────────────────
    @property
    def preferences(self) -> dict:
        """Retourne les préférences de l'utilisateur sous forme de dict."""
        if self._preferences:
            try:
                return json.loads(self._preferences)
            except (json.JSONDecodeError, TypeError):
                return {}
        return self._default_preferences()

    @preferences.setter
    def preferences(self, value: dict) -> None:
        """Enregistre les préférences en JSON."""
        self._preferences = json.dumps(value)

    @staticmethod
    def _default_preferences() -> dict:
        """Préférences par défaut."""
        return {
            "receive_daily": True,
            "receive_weekly": True,
            "daily_categories": [],
            "weekly_categories": [],
            "email_hour": 7,
            "timezone": "Europe/Paris",
        }

    @property
    def is_admin(self) -> bool:
        """Vérifie si l'utilisateur est administrateur."""
        return self.role == "admin"

    # ─── Méthodes de mot de passe ─────────────────────────────────────────
    def set_password(self, password: str) -> None:
        """Hache et enregistre le mot de passe."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Vérifie le mot de passe."""
        return check_password_hash(self.password_hash, password)

    # ─── Méthodes utilitaires ─────────────────────────────────────────────
    def update_last_login(self) -> None:
        """Met à jour la date de dernière connexion."""
        self.last_login = datetime.now(timezone.utc)
        db.session.commit()

    def get_preference(self, key: str, default=None):
        """Récupère une préférence spécifique."""
        return self.preferences.get(key, default)

    def set_preference(self, key: str, value) -> None:
        """Met à jour une préférence spécifique."""
        prefs = self.preferences
        prefs[key] = value
        self.preferences = prefs

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
