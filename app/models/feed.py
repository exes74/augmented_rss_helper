"""
Modèle de flux RSS.
"""
from datetime import datetime, timezone
from main import db


class Feed(db.Model):
    """Flux RSS souscrit par un utilisateur."""

    __tablename__ = "feeds"

    # Statuts possibles
    STATUS_ACTIVE = "active"
    STATUS_ERROR = "error"
    STATUS_DEAD = "dead"
    STATUS_PAUSED = "paused"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True, index=True)
    url = db.Column(db.String(2048), nullable=False)
    name = db.Column(db.String(255), nullable=True)  # Nom personnalisé ou auto-détecté
    description = db.Column(db.Text, nullable=True)
    favicon_url = db.Column(db.String(2048), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    status = db.Column(db.String(20), default=STATUS_ACTIVE, nullable=False)
    error_count = db.Column(db.Integer, default=0, nullable=False)
    error_log = db.Column(db.Text, nullable=True)
    last_fetched = db.Column(db.DateTime, nullable=True)
    last_article_at = db.Column(db.DateTime, nullable=True)
    articles_count = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # ─── Relations ────────────────────────────────────────────────────────
    articles = db.relationship("Article", backref="feed", lazy="dynamic",
                                cascade="all, delete-orphan")

    # ─── Contrainte d'unicité ─────────────────────────────────────────────
    __table_args__ = (
        db.UniqueConstraint("user_id", "url", name="uq_feed_user_url"),
    )

    @property
    def is_dead(self) -> bool:
        """Vérifie si le flux est marqué comme mort."""
        return self.status == self.STATUS_DEAD

    @property
    def display_name(self) -> str:
        """Retourne le nom d'affichage du flux."""
        return self.name or self.url

    def record_error(self, error_message: str, threshold: int = 3) -> bool:
        """
        Enregistre une erreur de collecte.
        Retourne True si le flux vient d'être marqué comme mort.
        """
        self.error_count += 1
        self.status = self.STATUS_ERROR
        self.error_log = error_message[:1000]  # Limite la taille du log

        if self.error_count >= threshold:
            self.status = self.STATUS_DEAD
            self.active = False
            return True
        return False

    def reset_errors(self) -> None:
        """Réinitialise le compteur d'erreurs après une collecte réussie."""
        self.error_count = 0
        self.status = self.STATUS_ACTIVE
        self.error_log = None

    def __repr__(self) -> str:
        return f"<Feed {self.display_name} ({self.status})>"
