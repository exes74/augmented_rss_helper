"""
Modèle d'article RSS collecté.
"""
import hashlib
from datetime import datetime, timezone
from main import db


class Article(db.Model):
    """Article collecté depuis un flux RSS."""

    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    feed_id = db.Column(db.Integer, db.ForeignKey("feeds.id"), nullable=False, index=True)
    title = db.Column(db.String(1024), nullable=False)
    url = db.Column(db.String(2048), nullable=False)
    content = db.Column(db.Text, nullable=True)   # Contenu ou résumé de l'article
    author = db.Column(db.String(255), nullable=True)
    published_at = db.Column(db.DateTime, nullable=True, index=True)
    fetched_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           nullable=False, index=True)
    hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)

    # ─── Contrainte d'unicité ─────────────────────────────────────────────
    __table_args__ = (
        db.Index("ix_articles_feed_published", "feed_id", "published_at"),
    )

    @staticmethod
    def compute_hash(url: str, title: str) -> str:
        """Calcule un hash unique pour dédupliquer les articles."""
        content = f"{url}|{title}".encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def exists(cls, url: str, title: str) -> bool:
        """Vérifie si un article existe déjà (déduplication)."""
        h = cls.compute_hash(url, title)
        return cls.query.filter_by(hash=h).first() is not None

    @property
    def short_content(self) -> str:
        """Retourne un extrait du contenu (300 caractères max)."""
        if self.content:
            return self.content[:300] + ("..." if len(self.content) > 300 else "")
        return ""

    def __repr__(self) -> str:
        return f"<Article {self.title[:50]}>"
