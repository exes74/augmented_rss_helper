"""
Routes du tableau de bord principal.
"""
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template
from flask_login import login_required, current_user

from main import db
from models.feed import Feed
from models.synthesis import Synthesis
from models.article import Article

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def index():
    """Vue d'ensemble : dernières synthèses et statut des flux."""
    # Dernières synthèses (5 dernières)
    recent_syntheses = (
        Synthesis.query
        .filter_by(user_id=current_user.id)
        .order_by(Synthesis.generated_at.desc())
        .limit(5)
        .all()
    )

    # Statut des flux
    feeds_stats = {
        "total": Feed.query.filter_by(user_id=current_user.id).count(),
        "active": Feed.query.filter_by(user_id=current_user.id, status="active").count(),
        "error": Feed.query.filter_by(user_id=current_user.id, status="error").count(),
        "dead": Feed.query.filter_by(user_id=current_user.id, status="dead").count(),
    }

    # Articles des dernières 24h
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    articles_today = (
        db.session.query(Article)
        .join(Article.feed)
        .filter(
            Feed.user_id == current_user.id,
            Article.fetched_at >= since
        )
        .count()
    )

    # Flux en erreur
    error_feeds = (
        Feed.query
        .filter_by(user_id=current_user.id)
        .filter(Feed.status.in_(["error", "dead"]))
        .order_by(Feed.error_count.desc())
        .limit(5)
        .all()
    )

    # Synthèse quotidienne du jour (si disponible)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_synthesis_today = (
        Synthesis.query
        .filter_by(user_id=current_user.id, type=Synthesis.TYPE_DAILY)
        .filter(Synthesis.generated_at >= today_start)
        .first()
    )

    return render_template(
        "dashboard.html",
        recent_syntheses=recent_syntheses,
        feeds_stats=feeds_stats,
        articles_today=articles_today,
        error_feeds=error_feeds,
        daily_synthesis_today=daily_synthesis_today,
    )
