"""
Modèle de synthèse IA.
"""
from datetime import datetime, timezone
from main import db


class Synthesis(db.Model):
    """Synthèse générée par l'IA pour un utilisateur et une catégorie."""

    __tablename__ = "syntheses"

    TYPE_DAILY = "daily"
    TYPE_WEEKLY = "weekly"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True, index=True)
    type = db.Column(db.String(10), nullable=False)  # daily | weekly
    content = db.Column(db.Text, nullable=True)          # Synthèse principale
    draft_linkedin = db.Column(db.Text, nullable=True)   # Draft post LinkedIn (hebdo)
    key_facts = db.Column(db.Text, nullable=True)        # Faits marquants (hebdo)
    trends = db.Column(db.Text, nullable=True)           # Tendances observées (hebdo)
    articles_count = db.Column(db.Integer, default=0, nullable=False)
    tokens_used = db.Column(db.Integer, default=0, nullable=False)
    generated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                             nullable=False, index=True)
    period_start = db.Column(db.DateTime, nullable=True)  # Début de la période couverte
    period_end = db.Column(db.DateTime, nullable=True)    # Fin de la période couverte
    email_sent = db.Column(db.Boolean, default=False, nullable=False)
    email_sent_at = db.Column(db.DateTime, nullable=True)

    # ─── Index composite ──────────────────────────────────────────────────
    __table_args__ = (
        db.Index("ix_synthesis_user_type_date", "user_id", "type", "generated_at"),
    )

    @property
    def is_daily(self) -> bool:
        return self.type == self.TYPE_DAILY

    @property
    def is_weekly(self) -> bool:
        return self.type == self.TYPE_WEEKLY

    @property
    def period_label(self) -> str:
        """Retourne un libellé lisible de la période."""
        if self.period_start and self.period_end:
            if self.is_daily:
                return self.period_start.strftime("%d/%m/%Y")
            else:
                return (f"{self.period_start.strftime('%d/%m')} – "
                        f"{self.period_end.strftime('%d/%m/%Y')}")
        return self.generated_at.strftime("%d/%m/%Y")

    def __repr__(self) -> str:
        return f"<Synthesis {self.type} user={self.user_id} cat={self.category_id}>"
