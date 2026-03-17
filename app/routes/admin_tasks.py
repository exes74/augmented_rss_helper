"""
Routes d'administration des tâches Celery.
Permet de déclencher manuellement la collecte RSS, les synthèses et les emails,
et de diagnostiquer l'état de Celery/Redis.
"""
import logging
from functools import wraps
from datetime import date, datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, current_app)
from flask_login import login_required, current_user
from main import db

logger = logging.getLogger(__name__)
admin_tasks_bp = Blueprint("admin_tasks", __name__, url_prefix="/admin/tasks")


def admin_required(f):
    """Décorateur : accès réservé aux administrateurs."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import abort
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


@admin_tasks_bp.route("/")
@login_required
@admin_required
def index():
    """Tableau de bord des tâches Celery avec état de santé."""
    from models.feed import Feed
    from models.article import Article
    from models.synthesis import Synthesis

    # Statistiques rapides
    total_articles = (
        Article.query
        .join(Article.feed)
        .filter(Feed.user_id == current_user.id)
        .count()
    )
    enriched_articles = (
        Article.query
        .join(Article.feed)
        .filter(Feed.user_id == current_user.id, Article.enriched == True)
        .count()
    )
    stats = {
        "total_feeds": Feed.query.filter_by(user_id=current_user.id).count(),
        "active_feeds": Feed.query.filter_by(user_id=current_user.id, active=True).count(),
        "total_articles": total_articles,
        "enriched_articles": enriched_articles,
        "enriched_pct": round(enriched_articles * 100 / total_articles) if total_articles else 0,
        "total_syntheses": Synthesis.query.filter_by(user_id=current_user.id).count(),
    }

    # Derniers flux collectés
    recent_feeds = (
        Feed.query
        .filter_by(user_id=current_user.id)
        .filter(Feed.last_fetched.isnot(None))
        .order_by(Feed.last_fetched.desc())
        .limit(10)
        .all()
    )

    # Dernières synthèses
    recent_syntheses = (
        Synthesis.query
        .filter_by(user_id=current_user.id)
        .order_by(Synthesis.generated_at.desc())
        .limit(5)
        .all()
    )

    # Tableau articles par source sur 7 jours
    from datetime import timedelta
    from sqlalchemy import func
    from models.category import Category
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    articles_by_source = (
        db.session.query(
            Feed.name.label('feed_name'),
            Feed.url.label('feed_url'),
            Category.name.label('category_name'),
            func.count(Article.id).label('article_count'),
            func.max(Article.published_at).label('last_article')
        )
        .join(Article, Article.feed_id == Feed.id)
        .outerjoin(Category, Feed.category_id == Category.id)
        .filter(
            Feed.user_id == current_user.id,
            Article.published_at >= seven_days_ago
        )
        .group_by(Feed.id, Feed.name, Feed.url, Category.name)
        .order_by(func.count(Article.id).desc())
        .all()
    )

    # État Celery
    celery_status = _check_celery_status()

    return render_template(
        "admin/tasks.html",
        stats=stats,
        recent_feeds=recent_feeds,
        recent_syntheses=recent_syntheses,
        celery_status=celery_status,
        articles_by_source=articles_by_source,
        today=date.today().isoformat(),
    )


@admin_tasks_bp.route("/run/fetch-rss", methods=["POST"])
@login_required
@admin_required
def run_fetch_rss():
    """Déclenche manuellement la collecte RSS."""
    try:
        from services.scheduler_tasks import fetch_all_feeds
        task = fetch_all_feeds.delay()
        flash(f"Collecte RSS lancée (task_id: {task.id}). Vérifiez les logs dans quelques secondes.", "success")
        logger.info(f"Collecte RSS déclenchée manuellement par {current_user.email}, task_id={task.id}")
    except Exception as e:
        flash(f"Erreur lors du lancement de la collecte RSS : {str(e)}", "danger")
        logger.error(f"Erreur déclenchement collecte RSS : {e}", exc_info=True)
    return redirect(url_for("admin_tasks.index"))


@admin_tasks_bp.route("/run/daily-synthesis", methods=["POST"])
@login_required
@admin_required
def run_daily_synthesis():
    """Déclenche manuellement la génération des synthèses quotidiennes."""
    target_date = request.form.get("target_date", date.today().isoformat())
    # force=True : toujours régénérer lors d'un déclenchement manuel
    force = request.form.get("force", "true").lower() != "false"
    try:
        from services.scheduler_tasks import generate_daily_syntheses
        task = generate_daily_syntheses.delay(target_date_str=target_date, force=force)
        force_label = " (régénération forcée)" if force else ""
        flash(f"Génération des synthèses quotidiennes lancée pour le {target_date}{force_label} (task_id: {task.id}).", "success")
        logger.info(f"Synthèses quotidiennes déclenchées par {current_user.email}, date={target_date}, force={force}")
    except Exception as e:
        flash(f"Erreur lors du lancement des synthèses : {str(e)}", "danger")
        logger.error(f"Erreur déclenchement synthèses quotidiennes : {e}", exc_info=True)
    return redirect(url_for("admin_tasks.index"))


@admin_tasks_bp.route("/run/weekly-synthesis", methods=["POST"])
@login_required
@admin_required
def run_weekly_synthesis():
    """Déclenche manuellement la génération des synthèses hebdomadaires."""
    # force=True : toujours régénérer lors d'un déclenchement manuel
    force = request.form.get("force", "true").lower() != "false"
    try:
        from services.scheduler_tasks import generate_weekly_syntheses
        task = generate_weekly_syntheses.delay(force=force)
        force_label = " (régénération forcée)" if force else ""
        flash(f"Génération des synthèses hebdomadaires lancée{force_label} (task_id: {task.id}).", "success")
        logger.info(f"Synthèses hebdomadaires déclenchées par {current_user.email}, force={force}")
    except Exception as e:
        flash(f"Erreur lors du lancement des synthèses hebdomadaires : {str(e)}", "danger")
        logger.error(f"Erreur déclenchement synthèses hebdomadaires : {e}", exc_info=True)
    return redirect(url_for("admin_tasks.index"))


@admin_tasks_bp.route("/run/send-daily-emails", methods=["POST"])
@login_required
@admin_required
def run_send_daily_emails():
    """Déclenche manuellement l'envoi des emails quotidiens.
    force=True par défaut : renvoie même si l'email a déjà été envoyé.
    """
    target_date = request.form.get("target_date", date.today().isoformat())
    # force=True par défaut lors d'un déclenchement manuel
    force = request.form.get("force", "true").lower() != "false"
    try:
        from services.scheduler_tasks import send_daily_emails
        task = send_daily_emails.delay(target_date_str=target_date, force=force)
        force_label = " (renvoi forcé)" if force else ""
        flash(f"Envoi des emails quotidiens lancé pour le {target_date}{force_label} (task_id: {task.id}).", "success")
        logger.info(f"Emails quotidiens déclenchés par {current_user.email}, date={target_date}, force={force}")
    except Exception as e:
        flash(f"Erreur lors de l'envoi des emails : {str(e)}", "danger")
        logger.error(f"Erreur déclenchement emails quotidiens : {e}", exc_info=True)
    return redirect(url_for("admin_tasks.index"))


@admin_tasks_bp.route("/run/send-weekly-emails", methods=["POST"])
@login_required
@admin_required
def run_send_weekly_emails():
    """Déclenche manuellement l'envoi des emails hebdomadaires.
    force=True par défaut : renvoie même si l'email a déjà été envoyé.
    """
    force = request.form.get("force", "true").lower() != "false"
    try:
        from services.scheduler_tasks import send_weekly_emails
        task = send_weekly_emails.delay(force=force)
        force_label = " (renvoi forcé)" if force else ""
        flash(
            f"Envoi des emails hebdomadaires lancé{force_label} (task_id: {task.id}).",
            "success"
        )
        logger.info(
            f"Emails hebdomadaires déclenchés par {current_user.email}, force={force}"
        )
    except Exception as e:
        flash(f"Erreur lors de l'envoi des emails hebdomadaires : {str(e)}", "danger")
        logger.error(f"Erreur déclenchement emails hebdomadaires : {e}", exc_info=True)
    return redirect(url_for("admin_tasks.index"))


@admin_tasks_bp.route("/run/enrich-articles", methods=["POST"])
@login_required
@admin_required
def run_enrich_articles():
    """Déclenche manuellement l'enrichissement full-text des articles courts."""
    max_articles = int(request.form.get("max_articles", 200))
    try:
        from services.scheduler_tasks import enrich_articles
        task = enrich_articles.delay(max_articles=max_articles)
        flash(
            f"Enrichissement des articles lancé (max={max_articles}, task_id: {task.id}). "
            f"Les articles courts vont être enrichis en arrière-plan.",
            "success"
        )
        logger.info(
            f"Enrichissement articles déclenché par {current_user.email}, "
            f"max_articles={max_articles}"
        )
    except Exception as e:
        flash(f"Erreur lors du lancement de l'enrichissement : {str(e)}", "danger")
        logger.error(f"Erreur déclenchement enrichissement articles : {e}", exc_info=True)
    return redirect(url_for("admin_tasks.index"))


@admin_tasks_bp.route("/status")
@login_required
@admin_required
def status():
    """API JSON : état de Celery et des workers."""
    return jsonify(_check_celery_status())


def _check_celery_status() -> dict:
    """Vérifie l'état de Celery et Redis."""
    status = {
        "celery_reachable": False,
        "redis_reachable": False,
        "active_workers": [],
        "error": None,
    }
    try:
        from services.scheduler_tasks import celery_app
        # Ping des workers (timeout 3s)
        inspector = celery_app.control.inspect(timeout=3.0)
        active = inspector.active()
        if active is not None:
            status["celery_reachable"] = True
            status["active_workers"] = list(active.keys())
        else:
            status["error"] = "Aucun worker Celery ne répond (timeout 3s)"
    except Exception as e:
        status["error"] = str(e)

    try:
        import redis as redis_lib
        import os
        redis_url = os.environ.get("REDIS_URL", "redis://:redispass@redis:6379/0")
        r = redis_lib.from_url(redis_url, socket_connect_timeout=3)
        r.ping()
        status["redis_reachable"] = True
    except Exception as e:
        status["error"] = (status.get("error") or "") + f" | Redis: {str(e)}"

    return status
