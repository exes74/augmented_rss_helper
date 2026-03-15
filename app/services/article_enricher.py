"""
Service d'enrichissement asynchrone des articles RSS.

Logique :
- Pour chaque article dont le contenu est trop court (< ARTICLE_MIN_CONTENT_LENGTH),
  on visite l'URL de l'article et on extrait le contenu complet via newspaper3k.
- Un rate limiting par domaine évite de surcharger les serveurs sources.
- Les articles qui échouent (Cloudflare, paywall, timeout) conservent leur contenu
  d'origine sans régression.

Variables d'environnement :
    ARTICLE_MIN_CONTENT_LENGTH : seuil en caractères sous lequel on enrichit (défaut: 500)
    ARTICLE_ENRICH_TIMEOUT     : timeout HTTP par article en secondes (défaut: 15)
    ARTICLE_ENRICH_RATE_LIMIT  : délai minimum entre 2 requêtes vers le même domaine
                                  en secondes (défaut: 2)
    ARTICLE_ENRICH_MAX_WORKERS : nombre de threads parallèles (défaut: 5)
    ARTICLE_ENRICH_MAX_AGE_DAYS: n'enrichit que les articles de moins de N jours (défaut: 7)
    ARTICLE_ENRICH_USER_AGENT  : User-Agent HTTP utilisé pour visiter les articles
                                  (défaut: Firefox/128.0 Linux)
"""
import logging
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────
MIN_CONTENT_LENGTH = int(os.environ.get("ARTICLE_MIN_CONTENT_LENGTH", 500))
ENRICH_TIMEOUT = int(os.environ.get("ARTICLE_ENRICH_TIMEOUT", 15))
RATE_LIMIT_DELAY = float(os.environ.get("ARTICLE_ENRICH_RATE_LIMIT", 2.0))
MAX_WORKERS = int(os.environ.get("ARTICLE_ENRICH_MAX_WORKERS", 5))
MAX_AGE_DAYS = int(os.environ.get("ARTICLE_ENRICH_MAX_AGE_DAYS", 7))

# User-Agent configurable via .env
# Par défaut : navigateur Firefox standard, discret et légal
USER_AGENT = os.environ.get(
    "ARTICLE_ENRICH_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)

# ─── Rate limiter par domaine ─────────────────────────────────────────────────
_domain_last_request: Dict[str, float] = {}
_rate_limit_lock = threading.Lock()


def _wait_for_rate_limit(domain: str) -> None:
    """
    Attend si nécessaire pour respecter le rate limit par domaine.
    Thread-safe via un verrou global.
    """
    with _rate_limit_lock:
        last = _domain_last_request.get(domain, 0.0)
        elapsed = time.time() - last
        if elapsed < RATE_LIMIT_DELAY:
            wait_time = RATE_LIMIT_DELAY - elapsed
            time.sleep(wait_time)
        _domain_last_request[domain] = time.time()


def _get_domain(url: str) -> str:
    """Extrait le domaine d'une URL."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return url


def fetch_full_content(url: str) -> Tuple[Optional[str], str]:
    """
    Télécharge et extrait le contenu complet d'un article via newspaper3k.

    Returns:
        Tuple (contenu_texte, message_erreur)
        - contenu_texte : texte nettoyé de l'article, ou None en cas d'échec
        - message_erreur : description de l'erreur, ou "" si succès
    """
    if not url or not url.startswith(("http://", "https://")):
        return None, "URL invalide"

    domain = _get_domain(url)

    try:
        # Rate limiting par domaine
        _wait_for_rate_limit(domain)

        # Import ici pour éviter l'import au niveau module si newspaper3k absent
        import newspaper
        from newspaper import Article as NewspaperArticle
        from newspaper.configuration import Configuration

        config = Configuration()
        config.browser_user_agent = USER_AGENT
        config.request_timeout = ENRICH_TIMEOUT
        config.fetch_images = False          # Pas besoin des images
        config.memoize_articles = False      # Pas de cache interne newspaper
        config.language = "fr"               # Priorité au français, fallback auto

        article = NewspaperArticle(url, config=config)
        article.download()
        article.parse()

        text = article.text.strip() if article.text else ""

        if not text:
            return None, "Contenu vide après extraction"

        # Nettoyer les espaces excessifs
        text = " ".join(text.split())

        logger.debug(f"Enrichissement OK : {url[:80]} ({len(text)} caractères)")
        return text, ""

    except ImportError:
        return None, "newspaper3k non installé"
    except Exception as e:
        error_msg = str(e)[:200]
        # Ne pas logger en ERROR pour les erreurs attendues (403, paywall, timeout)
        if any(code in error_msg for code in ["403", "404", "429", "paywall", "timeout"]):
            logger.debug(f"Enrichissement ignoré ({error_msg[:60]}) : {url[:80]}")
        else:
            logger.warning(f"Enrichissement échoué pour {url[:80]} : {error_msg}")
        return None, error_msg


def needs_enrichment(content: Optional[str]) -> bool:
    """
    Détermine si un article nécessite un enrichissement.
    Un article est considéré "pauvre" si son contenu est absent ou trop court.
    """
    if not content:
        return True
    # Supprimer les espaces pour une mesure plus précise
    clean = " ".join(content.split())
    return len(clean) < MIN_CONTENT_LENGTH


def enrich_articles_batch(app, max_articles: int = 200) -> Dict:
    """
    Enrichit un lot d'articles dont le contenu est trop court.

    Traitement séquentiel avec rate limiting par domaine.
    Appelé depuis la tâche Celery enrich_articles.

    Args:
        app       : instance Flask pour le contexte de base de données
        max_articles : nombre maximum d'articles à traiter par exécution

    Returns:
        Dictionnaire de statistiques {enriched, skipped, failed, total_processed}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    stats = {
        "total_processed": 0,
        "enriched": 0,
        "skipped": 0,
        "failed": 0,
    }

    with app.app_context():
        from models.article import Article
        from main import db

        # Fenêtre temporelle : articles récents uniquement
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)

        # Sélectionner les articles à enrichir :
        # - contenu absent OU contenu court (< MIN_CONTENT_LENGTH)
        # - publiés ou collectés récemment
        # - pas encore enrichis (on utilise un champ dédié si disponible,
        #   sinon on se base sur la longueur du contenu)
        candidates = (
            Article.query
            .filter(
                db.or_(
                    Article.content.is_(None),
                    db.func.length(Article.content) < MIN_CONTENT_LENGTH
                ),
                db.or_(
                    Article.fetched_at >= cutoff_date,
                    Article.published_at >= cutoff_date
                )
            )
            .order_by(Article.fetched_at.desc())
            .limit(max_articles)
            .all()
        )

        if not candidates:
            logger.info("Enrichissement : aucun article à enrichir.")
            return stats

        logger.info(
            f"Enrichissement : {len(candidates)} articles candidats "
            f"(contenu < {MIN_CONTENT_LENGTH} caractères, "
            f"fenêtre {MAX_AGE_DAYS} jours)"
        )

        stats["total_processed"] = len(candidates)

        # Traitement avec pool de threads pour paralléliser les requêtes HTTP
        # tout en respectant le rate limiting par domaine
        def _process_article(article_id: int, url: str) -> Tuple[int, Optional[str], str]:
            """Enrichit un article et retourne (id, contenu, erreur)."""
            content, error = fetch_full_content(url)
            return article_id, content, error

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_process_article, a.id, a.url): a.id
                for a in candidates
            }

            for future in as_completed(futures):
                article_id, new_content, error = future.result()

                if new_content and len(new_content) > MIN_CONTENT_LENGTH:
                    # Mettre à jour dans un nouveau contexte app pour éviter
                    # les conflits de session SQLAlchemy entre threads
                    try:
                        article = Article.query.get(article_id)
                        if article:
                            article.content = new_content[:50000]  # cap à 50k chars
                            article.enriched = True
                            db.session.commit()
                            stats["enriched"] += 1
                            logger.debug(
                                f"Article #{article_id} enrichi : "
                                f"{len(new_content)} caractères"
                            )
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Erreur DB lors de l'enrichissement #{article_id}: {e}")
                        stats["failed"] += 1
                elif error:
                    stats["failed"] += 1
                else:
                    # Contenu extrait mais toujours trop court → on ne met pas à jour
                    stats["skipped"] += 1

    logger.info(
        f"Enrichissement terminé : "
        f"{stats['enriched']} enrichis, "
        f"{stats['skipped']} ignorés (contenu toujours court), "
        f"{stats['failed']} échecs "
        f"sur {stats['total_processed']} traités"
    )
    return stats
