"""
Modèle d'abonnement aux synthèses (partage inter-comptes ou emails tiers).
"""
from datetime import datetime, timezone
from main import db


class Subscription(db.Model):
    """
    Abonnement permettant à un email tiers de recevoir les synthèses
    d'un utilisateur sans accès à l'interface.
    """

    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subscriber_email = db.Column(db.String(255), nullable=False)
    subscriber_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    confirmed = db.Column(db.Boolean, default=False, nullable=False)
    confirmation_token = db.Column(db.String(128), nullable=True)
    receive_daily = db.Column(db.Boolean, default=True, nullable=False)
    receive_weekly = db.Column(db.Boolean, default=True, nullable=False)
    categories = db.Column(db.Text, nullable=True)  # JSON list of category IDs
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    # ─── Contrainte d'unicité ─────────────────────────────────────────────
    __table_args__ = (
        db.UniqueConstraint("owner_user_id", "subscriber_email",
                            name="uq_subscription_owner_email"),
    )

    def __repr__(self) -> str:
        return f"<Subscription {self.subscriber_email} -> user={self.owner_user_id}>"
