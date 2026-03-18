"""
Tâches Celery pour la collecte RSS, la génération de synthèses et l'envoi d'emails.
Celery Beat gère la planification automatique (cron jobs).

CORRECTIONS APPLIQUÉES :
1. Suppression des queues multiples (feeds/synthesis/emails) → une seule queue "celery"
   car le worker est lancé sans --queues spécifique
2. Intégration du contexte Flask directement dans make_celery() via ContextTask
3. Collecte RSS toutes les heures (pas seulement à 6h) pour ne pas attendre 24h
4. Correction du task_routes qui pointait vers des queues inexistantes
"""
import logging
import os
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional

from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def make_celery(flask_app=None) -> Celery:
    """
    Crée et configure l'instance Celery.
    Peut être utilisé avec ou sans contexte Flask.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://:redispass@redis:6379/0")

    celery_instance = Celery(
        "rss_veille",
        broker=redis_url,
        backend=redis_url,
    )

    celery_instance.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone=os.environ.get("TIMEZONE", "Europe/Paris"),
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # CORRECTION 1 : Pas de task_routes vers des queues multiples
        # Le worker est lancé sans --queues, donc tout va dans la queue "celery" par défaut
        task_default_queue="celery",
        broker_connection_retry_on_startup=True,
    )

    # ─── Planification Celery Beat ────────────────────────────────────────
    rss_hour = int(os.environ.get("RSS_FETCH_HOUR", 6))
    rss_minute = int(os.environ.get("RSS_FETCH_MINUTE", 0))
    daily_hour = int(os.environ.get("DAILY_SYNTHESIS_HOUR", 7))
    daily_minute = int(os.environ.get("DAILY_SYNTHESIS_MINUTE", 0))
    # Synthèses hebdomadaires : mercredi 7h00 par défaut
    # (configurable via WEEKLY_SYNTHESIS_HOUR et WEEKLY_SYNTHESIS_DAY)
    weekly_hour = int(os.environ.get("WEEKLY_SYNTHESIS_HOUR", 7))
    weekly_minute = int(os.environ.get("WEEKLY_SYNTHESIS_MINUTE", 0))
    weekly_day = os.environ.get("WEEKLY_SYNTHESIS_DAY", "wednesday")

    day_map = {
        "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4,
        "friday": 5, "saturday": 6, "sunday": 0
    }
    weekly_day_num = day_map.get(weekly_day.lower(), 3)  # 3 = mercredi

    celery_instance.conf.beat_schedule = {
        # Collecte RSS toutes les heures
        "fetch-all-feeds-hourly": {
            "task": "services.scheduler_tasks.fetch_all_feeds",
            "schedule": crontab(minute=rss_minute),
        },
        # Synthèses quotidiennes (7h00 par défaut)
        "generate-daily-syntheses": {
            "task": "services.scheduler_tasks.generate_daily_syntheses",
            "schedule": crontab(hour=daily_hour, minute=daily_minute),
        },
        # Envoi emails quotidiens (30 min après les synthèses)
        "send-daily-emails": {
            "task": "services.scheduler_tasks.send_daily_emails",
            "schedule": crontab(hour=daily_hour, minute=(daily_minute + 30) % 60),
        },
        # Super-synthèse hebdomadaire : mercredi 7h00
        # Prend les 7 derniers jours glissants de synthèses quotidiennes disponibles
        "generate-weekly-syntheses": {
            "task": "services.scheduler_tasks.generate_weekly_syntheses",
            "schedule": crontab(hour=weekly_hour, minute=weekly_minute,
                                day_of_week=weekly_day_num),
        },
        # Envoi emails hebdomadaires : mercredi 7h30 (30 min après la génération)
        "send-weekly-emails": {
            "task": "services.scheduler_tasks.send_weekly_emails",
            "schedule": crontab(hour=weekly_hour, minute=(weekly_minute + 30) % 60,
                                day_of_week=weekly_day_num),
        },
        # Nettoyage des anciens articles (tous les dimanches à 3h00)
        "cleanup-old-articles": {
            "task": "services.scheduler_tasks.cleanup_old_articles",
            "schedule": crontab(hour=3, minute=0, day_of_week=0),
        },
        # Enrichissement des articles courts : 30 min après chaque collecte RSS
        # Configurable via ARTICLE_ENRICH_MINUTE (défaut: 30 min après rss_minute)
        "enrich-articles": {
            "task": "services.scheduler_tasks.enrich_articles",
            "schedule": crontab(minute=(rss_minute + 30) % 60),
        },
    }

    # CORRECTION 3 : Intégration du contexte Flask dans toutes les tâches
    # via ContextTask — évite le double app_context dans chaque tâche
    if flask_app is not None:
        class ContextTask(celery_instance.Task):
            def __call__(self, *args, **kwargs):
                with flask_app.app_context():
                    return self.run(*args, **kwargs)
        celery_instance.Task = ContextTask

    return celery_instance


# ─── Instance Celery globale ──────────────────────────────────────────────
# Créée sans Flask app ici ; le contexte Flask est géré manuellement dans chaque tâche
celery_app = make_celery()


def _get_flask_app():
    """Crée un contexte Flask pour les tâches Celery (appelé dans chaque tâche)."""
    import sys
    sys.path.insert(0, "/app")
    from main import create_app
    return create_app()


# ─── Tâche : Collecte de tous les flux RSS ────────────────────────────────
@celery_app.task(bind=True, name="services.scheduler_tasks.fetch_all_feeds",
                 max_retries=3, default_retry_delay=300)
def fetch_all_feeds(self):
    """
    Tâche principale de collecte RSS.
    Parcourt tous les flux actifs et collecte les nouveaux articles.
    """
    flask_app = _get_flask_app()
    with flask_app.app_context():
        from main import db
        from models.feed import Feed
        from models.article import Article
        from services.rss_fetcher import fetch_feed_articles
        from services.email_sender import send_feed_dead_notification

        logger.info("Démarrage de la collecte RSS globale")
        start_time = datetime.now(timezone.utc)

        active_feeds = Feed.query.filter_by(active=True).filter(
            Feed.status.in_([Feed.STATUS_ACTIVE, Feed.STATUS_ERROR])
        ).all()

        logger.info(f"Flux actifs à collecter : {len(active_feeds)}")
        stats = {"feeds_processed": 0, "articles_new": 0, "feeds_error": 0, "feeds_dead": 0}

        for feed in active_feeds:
            try:
                articles_data, error_msg = fetch_feed_articles(feed.url, feed.last_fetched)

                if error_msg:
                    became_dead = feed.record_error(
                        error_msg,
                        threshold=flask_app.config.get("FEED_ERROR_THRESHOLD", 3)
                    )
                    db.session.commit()
                    stats["feeds_error"] += 1
                    logger.warning(f"Erreur flux {feed.url}: {error_msg}")

                    if became_dead:
                        stats["feeds_dead"] += 1
                        logger.warning(f"Flux marqué comme mort : {feed.url}")
                        try:
                            send_feed_dead_notification(
                                feed.owner.email, feed.display_name, feed.url
                            )
                        except Exception as e:
                            logger.error(f"Erreur notification flux mort : {e}")
                    continue

                # Insérer les nouveaux articles
                new_count = 0
                for art_data in articles_data:
                    try:
                        if Article.exists(art_data["url"], art_data["title"]):
                            continue

                        # Troncature défensive des champs à longueur limitée
                        title = (art_data["title"] or "")[:1024]
                        url = (art_data["url"] or "")[:2048]
                        author = art_data.get("author") or ""

                        article = Article(
                            feed_id=feed.id,
                            title=title,
                            url=url,
                            content=art_data.get("content"),
                            author=author,
                            published_at=art_data.get("published_at"),
                            hash=art_data["hash"],
                        )
                        db.session.add(article)
                        db.session.flush()  # Détecte les erreurs DB immédiatement
                        new_count += 1
                    except Exception as art_err:
                        db.session.rollback()  # Réinitialise la session pour l'article suivant
                        logger.warning(
                            f"Article ignoré (flux {feed.id}, titre='{art_data.get('title', '')[:60]}'): {art_err}"
                        )

                feed.reset_errors()
                feed.last_fetched = datetime.now(timezone.utc)
                feed.articles_count = (feed.articles_count or 0) + new_count
                if new_count > 0:
                    feed.last_article_at = datetime.now(timezone.utc)

                db.session.commit()
                stats["feeds_processed"] += 1
                stats["articles_new"] += new_count
                logger.info(f"Flux {feed.display_name} : {new_count} nouveaux articles")

            except Exception as e:
                logger.error(f"Erreur inattendue pour le flux {feed.id} ({feed.url}): {e}")
                db.session.rollback()
                stats["feeds_error"] += 1

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            f"Collecte RSS terminée en {duration:.1f}s : "
            f"{stats['feeds_processed']} flux traités, "
            f"{stats['articles_new']} nouveaux articles, "
            f"{stats['feeds_error']} erreurs, "
            f"{stats['feeds_dead']} flux morts"
        )
        return stats


# ─── Tâche : Enrichissement des articles courts ────────────────────────
@celery_app.task(bind=True, name="services.scheduler_tasks.enrich_articles",
                 max_retries=1, default_retry_delay=300)
def enrich_articles(self, max_articles: int = 200):
    """
    Enrichit les articles dont le contenu est trop court en visitant leur URL
    et en extrayant le contenu complet via newspaper3k.

    Planifié automatiquement 30 min après chaque collecte RSS.
    Peut aussi être déclenché manuellement depuis /admin/tasks.

    Args:
        max_articles : nombre maximum d'articles à traiter par exécution
    """
    flask_app = _get_flask_app()
    try:
        from services.article_enricher import enrich_articles_batch
        logger.info(
            f"Démarrage de l'enrichissement des articles "
            f"(max={max_articles}, seuil={os.environ.get('ARTICLE_MIN_CONTENT_LENGTH', 500)} chars)"
        )
        stats = enrich_articles_batch(flask_app, max_articles=max_articles)
        logger.info(
            f"Enrichissement terminé : "
            f"{stats['enriched']} enrichis, "
            f"{stats['skipped']} ignorés, "
            f"{stats['failed']} échecs "
            f"sur {stats['total_processed']} traités"
        )
        return stats
    except Exception as e:
        logger.error(f"Erreur lors de l'enrichissement des articles : {e}")
        raise self.retry(exc=e)


# ─── Tâche : Génération des synthèses quotidiennes ────────────────────────
@celery_app.task(bind=True, name="services.scheduler_tasks.generate_daily_syntheses",
                 max_retries=2, default_retry_delay=600)
def generate_daily_syntheses(self, target_date_str: Optional[str] = None, force: bool = False):
    """
    Génère les synthèses quotidiennes pour tous les utilisateurs et catégories.
    Si force=True, supprime les synthèses existantes du jour avant de régénérer.
    """
    flask_app = _get_flask_app()
    with flask_app.app_context():
        from main import db
        from models.user import User
        from models.category import Category
        from models.article import Article
        from models.feed import Feed
        from models.synthesis import Synthesis
        from services.ai_synthesizer import get_synthesizer

        if target_date_str:
            target_date = date.fromisoformat(target_date_str)
        else:
            # En mode automatique (sans date cible), on synthétise la VEILLE
            # car la tâche tourne à 7h du matin et les articles de la veille
            # sont ceux qui ont été publiés le jour précédent
            target_date = date.today() - timedelta(days=1)

        logger.info(f"Génération des synthèses quotidiennes pour le {target_date}")

        synthesizer = get_synthesizer(flask_app)
        stats = {"users_processed": 0, "syntheses_generated": 0, "errors": 0}

        day_start = datetime.combine(target_date, datetime.min.time()).replace(
            tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        users = User.query.filter_by(is_active=True).all()
        logger.info(f"Utilisateurs actifs : {len(users)}")

        for user in users:
            try:
                categories = Category.query.filter_by(
                    user_id=user.id, active=True
                ).all()

                for category in categories:
                    existing = Synthesis.query.filter_by(
                        user_id=user.id,
                        category_id=category.id,
                        type=Synthesis.TYPE_DAILY,
                    ).filter(
                        Synthesis.generated_at >= day_start,
                        Synthesis.generated_at < day_end,
                    ).first()

                    if existing:
                        if not force:
                            logger.debug(f"Synthèse déjà existante pour user={user.id}, cat={category.name} (utilisez force=True pour régénérer)")
                            continue
                        # force=True : supprimer l'ancienne synthèse avant de régénérer
                        logger.info(f"Force=True : suppression synthèse existante user={user.id}, cat={category.name}")
                        db.session.delete(existing)
                        db.session.commit()

                    # CORRECTION : filtrer par published_at (date de publication)
                    # et non par fetched_at (date de collecte)
                    articles = (
                        db.session.query(Article)
                        .join(Article.feed)
                        .filter(
                            Feed.user_id == user.id,
                            Feed.category_id == category.id,
                            Article.published_at >= day_start,
                            Article.published_at < day_end,
                        )
                        .order_by(Article.published_at.desc())
                        .all()
                    )

                    if not articles:
                        logger.debug(f"Aucun article publié le {target_date} pour user={user.id}, cat={category.name}")
                        continue

                    logger.info(f"Génération synthèse : user={user.id}, cat={category.name}, {len(articles)} articles")

                    articles_data = [
                        {
                            "title": a.title,
                            "url": a.url,
                            "content": a.content,
                            "published_at": a.published_at,
                            "feed_name": a.feed.display_name if a.feed else "",
                        }
                        for a in articles
                    ]

                    content, tokens_used = synthesizer.generate_daily_synthesis(
                        articles_data, category.name, target_date
                    )

                    synthesis = Synthesis(
                        user_id=user.id,
                        category_id=category.id,
                        type=Synthesis.TYPE_DAILY,
                        content=content,
                        articles_count=len(articles),
                        tokens_used=tokens_used,
                        period_start=day_start,
                        period_end=day_end,
                    )
                    db.session.add(synthesis)
                    db.session.commit()
                    stats["syntheses_generated"] += 1
                    logger.info(f"Synthèse quotidienne créée : user={user.id}, cat={category.name}, tokens={tokens_used}")

                stats["users_processed"] += 1

            except Exception as e:
                logger.error(f"Erreur synthèse quotidienne user={user.id}: {e}", exc_info=True)
                db.session.rollback()
                stats["errors"] += 1

        logger.info(
            f"Synthèses quotidiennes terminées : {stats['users_processed']} utilisateurs, "
            f"{stats['syntheses_generated']} synthèses générées, {stats['errors']} erreurs"
        )
        return stats


# ─── Tâche : Génération des synthèses hebdomadaires ──────────────────────
@celery_app.task(bind=True, name="services.scheduler_tasks.generate_weekly_syntheses",
                 max_retries=2, default_retry_delay=600)
def generate_weekly_syntheses(self, force: bool = False):
    """
    Génère les synthèses hebdomadaires sous forme de "super-synthèse" :
    agrège les synthèses QUOTIDIENNES des 7 DERNIERS JOURS GLISSANTS par catégorie,
    puis demande au LLM de produire une synthèse de synthèses.

    La fenêtre est toujours J-7 → hier (7 jours glissants).
    Si certains jours n'ont pas de synthèse, on prend ce qui est disponible.
    Si force=True, supprime les synthèses hebdo existantes avant de régénérer.
    """
    flask_app = _get_flask_app()
    with flask_app.app_context():
        from main import db
        from models.user import User
        from models.category import Category
        from models.synthesis import Synthesis
        from services.ai_synthesizer import get_synthesizer

        today = date.today()
        # Fenêtre glissante : les 7 derniers jours inclus aujourd'hui (J-6 → aujourd'hui)
        # On inclut aujourd'hui pour que les synthèses du jour soient prises en compte
        # lors d'un déclenchement manuel ou automatique le mercredi matin
        period_end = today
        period_start = period_end - timedelta(days=6)   # il y a 6 jours (= 7 jours au total)

        week_start_dt = datetime.combine(period_start, datetime.min.time()).replace(
            tzinfo=timezone.utc)
        week_end_dt = datetime.combine(period_end, datetime.max.time()).replace(
            tzinfo=timezone.utc)

        logger.info(
            f"Génération des super-synthèses hebdomadaires "
            f"(fenêtre glissante : {period_start} → {period_end})"
        )

        synthesizer = get_synthesizer(flask_app)
        stats = {"users_processed": 0, "syntheses_generated": 0, "errors": 0}

        users = User.query.filter_by(is_active=True).all()

        for user in users:
            try:
                categories = Category.query.filter_by(
                    user_id=user.id, active=True
                ).all()

                for category in categories:
                    # Vérifier si une synthèse hebdo existe déjà pour cette semaine
                    existing = Synthesis.query.filter_by(
                        user_id=user.id,
                        category_id=category.id,
                        type=Synthesis.TYPE_WEEKLY,
                    ).filter(
                        Synthesis.period_start >= week_start_dt,
                        Synthesis.period_start <= week_end_dt,
                    ).first()

                    if existing:
                        if not force:
                            logger.debug(
                                f"Super-synthèse hebdo déjà existante "
                                f"user={user.id}, cat={category.name}"
                            )
                            continue
                        logger.info(
                            f"Force=True : suppression super-synthèse hebdo existante "
                            f"user={user.id}, cat={category.name}"
                        )
                        db.session.delete(existing)
                        db.session.commit()

                    # Récupérer les synthèses QUOTIDIENNES de la semaine précédente
                    daily_syntheses = Synthesis.query.filter_by(
                        user_id=user.id,
                        category_id=category.id,
                        type=Synthesis.TYPE_DAILY,
                    ).filter(
                        Synthesis.generated_at >= week_start_dt,
                        Synthesis.generated_at <= week_end_dt,
                    ).order_by(Synthesis.generated_at.asc()).all()

                    if not daily_syntheses:
                        logger.info(
                            f"Aucune synthèse quotidienne disponible sur les 7 derniers jours "
                            f"({period_start} → {period_end}) — user={user.id}, cat={category.name} — ignoré"
                        )
                        continue

                    logger.info(
                        f"Super-synthèse hebdo : user={user.id}, cat={category.name}, "
                        f"{len(daily_syntheses)} synthèses quotidiennes disponibles "
                        f"(sur 7 jours demandés)"
                    )

                    # Préparer les données des synthèses quotidiennes pour le LLM
                    daily_data = [
                        {
                            "date": s.generated_at.strftime("%d/%m/%Y") if s.generated_at else "",
                            "content": s.content or "",
                            "articles_count": s.articles_count or 0,
                        }
                        for s in daily_syntheses
                    ]

                    # Numéro de semaine ISO basé sur la date de fin de période
                    week_number = period_end.isocalendar()[1]

                    result, tokens_used = synthesizer.generate_weekly_synthesis(
                        daily_data, category.name, period_start, period_end,
                        week_number=week_number
                    )

                    total_articles = sum(s.articles_count or 0 for s in daily_syntheses)

                    synthesis = Synthesis(
                        user_id=user.id,
                        category_id=category.id,
                        type=Synthesis.TYPE_WEEKLY,
                        content=result.get("content", ""),
                        key_facts=result.get("key_facts", ""),
                        trends=result.get("trends", ""),
                        draft_linkedin=result.get("draft_linkedin", ""),
                        articles_count=total_articles,
                        tokens_used=tokens_used,
                        period_start=week_start_dt,
                        period_end=week_end_dt,
                    )
                    db.session.add(synthesis)
                    db.session.commit()
                    stats["syntheses_generated"] += 1
                    logger.info(
                        f"Super-synthèse hebdo créée : user={user.id}, "
                        f"cat={category.name}, tokens={tokens_used}"
                    )

                stats["users_processed"] += 1

            except Exception as e:
                logger.error(
                    f"Erreur super-synthèse hebdomadaire user={user.id}: {e}",
                    exc_info=True
                )
                db.session.rollback()
                stats["errors"] += 1

        logger.info(
            f"Super-synthèses hebdomadaires terminées : {stats['users_processed']} utilisateurs, "
            f"{stats['syntheses_generated']} synthèses générées"
        )
        return stats


# ─── Tâche : Envoi des emails quotidiens ─────────────────────────────────
@celery_app.task(bind=True, name="services.scheduler_tasks.send_daily_emails",
                 max_retries=3, default_retry_delay=300)
def send_daily_emails(self, target_date_str: Optional[str] = None, force: bool = False):
    """Envoie les emails de synthèse quotidienne à tous les utilisateurs abonnés.
    Si force=True, renvoie même si l'email a déjà été envoyé (email_sent=True).
    """
    flask_app = _get_flask_app()
    with flask_app.app_context():
        from main import db
        from models.user import User
        from models.synthesis import Synthesis
        from models.subscription import Subscription
        from services.email_sender import send_daily_synthesis_email

        if target_date_str:
            target_date = date.fromisoformat(target_date_str)
        else:
            target_date = date.today()

        day_start = datetime.combine(target_date, datetime.min.time()).replace(
            tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        logger.info(f"Envoi des emails quotidiens pour le {target_date} (force={force})")
        stats = {"emails_sent": 0, "errors": 0}

        users = User.query.filter_by(is_active=True).all()

        for user in users:
            prefs = user.preferences
            if not prefs.get("receive_daily", True):
                continue

            daily_cats = prefs.get("daily_categories", [])

            # CORRECTION BUG 2 : filtrer par period_start (date des articles synthétisés)
            # et non par generated_at (date de génération de la synthèse)
            # Ainsi un envoi forcé sur 2026-03-16 trouve bien la synthèse
            # générée le 17/03 mais couvrant les articles du 16/03
            query = Synthesis.query.filter_by(
                user_id=user.id, type=Synthesis.TYPE_DAILY
            ).filter(
                Synthesis.period_start >= day_start,
                Synthesis.period_start < day_end,
            )
            if not force:
                query = query.filter(Synthesis.email_sent == False)
            if daily_cats:
                query = query.filter(Synthesis.category_id.in_(daily_cats))

            syntheses = query.all()
            if not syntheses:
                continue

            from models.article import Article
            from models.feed import Feed

            # ─── Un email PAR catégorie ───────────────────────────────────
            for s in syntheses:
                cat_name = s.category.name if s.category else "Général"
                cat_id = s.category_id

                # Articles sources pour cette catégorie
                articles_raw = (
                    db.session.query(Article)
                    .join(Article.feed)
                    .filter(
                        Feed.user_id == user.id,
                        Feed.category_id == cat_id,
                        Article.published_at >= day_start,
                        Article.published_at < day_end,
                    )
                    .order_by(Article.published_at.desc())
                    .all()
                )
                articles_list = [
                    {
                        "title": a.title,
                        "url": a.url,
                        "feed_name": a.feed.display_name if a.feed else "",
                        "published_at": a.published_at,
                    }
                    for a in articles_raw
                ]

                synthesis_data = [{
                    "category_name": cat_name,
                    "content": s.content or "",
                    "articles_count": s.articles_count,
                    "articles": articles_list,
                }]

                # Destinataires : utilisateur + abonnés filtrés par catégorie
                to_emails = [user.email]
                subs = Subscription.query.filter_by(
                    owner_user_id=user.id, receive_daily=True
                ).all()
                for sub in subs:
                    # Si l'abonné a des catégories configurées, vérifier l'inclusion
                    import json
                    sub_cats = []
                    if sub.categories:
                        try:
                            sub_cats = json.loads(sub.categories)
                        except Exception:
                            sub_cats = []
                    # Inclure si pas de filtre catégorie ou si catégorie dans la liste
                    if not sub_cats or cat_id in sub_cats:
                        to_emails.append(sub.subscriber_email)

                try:
                    success = send_daily_synthesis_email(
                        to_emails, user.email, synthesis_data, target_date
                    )
                    if success:
                        s.email_sent = True
                        s.email_sent_at = datetime.now(timezone.utc)
                        db.session.commit()
                        stats["emails_sent"] += 1
                        logger.info(
                            f"Email quotidien [{cat_name}] envoyé à {user.email} "
                            f"+ {len(to_emails)-1} abonnés"
                        )
                    else:
                        stats["errors"] += 1
                except Exception as e:
                    logger.error(
                        f"Erreur envoi email quotidien [{cat_name}] user={user.id}: {e}"
                    )
                    stats["errors"] += 1

        logger.info(f"Emails quotidiens : {stats['emails_sent']} envoyés, {stats['errors']} erreurs")
        return stats


# ─── Tâche : Envoi des emails hebdomadaires ───────────────────────────────
@celery_app.task(bind=True, name="services.scheduler_tasks.send_weekly_emails",
                 max_retries=3, default_retry_delay=300)
def send_weekly_emails(self, force: bool = False):
    """Envoie les emails de synthèse hebdomadaire.
    Si force=True, renvoie même si l'email a déjà été envoyé (email_sent=True).
    """
    flask_app = _get_flask_app()
    with flask_app.app_context():
        from main import db
        from models.user import User
        from models.synthesis import Synthesis
        from models.subscription import Subscription
        from services.email_sender import send_weekly_synthesis_email

        today = date.today()
        # Fenêtre glissante : J-6 → aujourd'hui (7 jours au total, aujourd'hui inclus)
        # Cohérent avec generate_weekly_syntheses
        period_end = today
        period_start = period_end - timedelta(days=6)
        week_start_dt = datetime.combine(period_start, datetime.min.time()).replace(
            tzinfo=timezone.utc)
        week_end_dt = datetime.combine(period_end, datetime.max.time()).replace(
            tzinfo=timezone.utc)

        logger.info(
            f"Envoi des emails hebdomadaires (fenêtre glissante : "
            f"{period_start} → {period_end}, force={force})"
        )
        stats = {"emails_sent": 0, "errors": 0}

        users = User.query.filter_by(is_active=True).all()

        for user in users:
            prefs = user.preferences
            if not prefs.get("receive_weekly", True):
                continue

            weekly_cats = prefs.get("weekly_categories", [])

            query = Synthesis.query.filter_by(
                user_id=user.id, type=Synthesis.TYPE_WEEKLY
            ).filter(
                Synthesis.period_start >= week_start_dt,
                Synthesis.period_start <= week_end_dt,
            )
            # En mode normal, ne renvoyer que les emails non encore envoyés
            if not force:
                query = query.filter(Synthesis.email_sent == False)

            if weekly_cats:
                query = query.filter(Synthesis.category_id.in_(weekly_cats))

            syntheses = query.all()

            if not syntheses:
                continue

            syntheses_data = []
            for s in syntheses:
                cat_name = s.category.name if s.category else "Général"
                syntheses_data.append({
                    "category_name": cat_name,
                    "content": s.content or "",
                    "key_facts": s.key_facts or "",
                    "trends": s.trends or "",
                    "draft_linkedin": s.draft_linkedin or "",
                    "articles_count": s.articles_count,
                })

            to_emails = [user.email]
            subs = Subscription.query.filter_by(
                owner_user_id=user.id, receive_weekly=True
            ).all()
            to_emails.extend([s.subscriber_email for s in subs])

            try:
                success = send_weekly_synthesis_email(
                    to_emails, syntheses_data, period_start, period_end
                )
                if success:
                    for s in syntheses:
                        s.email_sent = True
                        s.email_sent_at = datetime.now(timezone.utc)
                    db.session.commit()
                    stats["emails_sent"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                logger.error(f"Erreur envoi email hebdo user={user.id}: {e}")
                stats["errors"] += 1

        logger.info(f"Emails hebdomadaires : {stats['emails_sent']} envoyés, {stats['errors']} erreurs")
        return stats


# ─── Tâche : Nettoyage des anciens articles ───────────────────────────────
@celery_app.task(name="services.scheduler_tasks.cleanup_old_articles")
def cleanup_old_articles():
    """Supprime les articles plus anciens que la durée de rétention configurée."""
    flask_app = _get_flask_app()
    with flask_app.app_context():
        from main import db
        from models.article import Article

        retention_days = int(os.environ.get("ARTICLES_RETENTION_DAYS", 90))
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        deleted = Article.query.filter(Article.fetched_at < cutoff).delete()
        db.session.commit()

        logger.info(f"Nettoyage : {deleted} articles supprimés (rétention {retention_days}j)")
        return {"deleted": deleted}
