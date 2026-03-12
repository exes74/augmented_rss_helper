"""
Modèle de catégorie RSS.
"""
from datetime import datetime, timezone
from main import db


class Category(db.Model):
    """Catégorie créée par un utilisateur pour organiser ses flux RSS."""

    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#3B82F6")  # Couleur hex
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # ─── Relations ────────────────────────────────────────────────────────
    feeds = db.relationship("Feed", backref="category", lazy="dynamic",
                             cascade="all, delete-orphan")
    syntheses = db.relationship("Synthesis", backref="category", lazy="dynamic",
                                 cascade="all, delete-orphan")

    # ─── Contrainte d'unicité par utilisateur ─────────────────────────────
    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_category_user_name"),
    )

    @property
    def feeds_count(self) -> int:
        """Nombre de flux actifs dans cette catégorie."""
        return self.feeds.filter_by(active=True).count()

    @property
    def articles_today_count(self) -> int:
        """Nombre d'articles collectés aujourd'hui dans cette catégorie."""
        from datetime import date
        from models.article import Article
        today = date.today()
        return (
            db.session.query(Article)
            .join(Article.feed)
            .filter(
                db.cast(Article.fetched_at, db.Date) == today,
                Article.feed.has(category_id=self.id)
            )
            .count()
        )

    def __repr__(self) -> str:
        return f"<Category {self.name} (user={self.user_id})>"
