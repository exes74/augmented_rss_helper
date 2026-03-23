"""
Service de collecte et validation des flux RSS.
Gère la récupération des articles, la déduplication et la gestion des erreurs.
"""
import logging
import hashlib
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, List, Optional
from urllib.parse import urlparse

import feedparser
import requests
from requests.exceptions import RequestException, Timeout

logger = logging.getLogger(__name__)

# Timeout pour les requêtes HTTP
REQUEST_TIMEOUT = 15  # secondes
USER_AGENT = "RSS-Veille/1.0 (+https://github.com/rss-veille)"


def validate_rss_url(url: str) -> Tuple[bool, Dict[str, Any], str]:
    """
    Valide une URL de flux RSS.

    Returns:
        Tuple (is_valid, feed_info, error_message)
    """
    if not url or not url.startswith(("http://", "https://")):
        return False, {}, "L'URL doit commencer par http:// ou https://"

    try:
        headers = {"User-Agent": USER_AGENT}
        response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers,
                                allow_redirects=True)
        response.raise_for_status()

        # Parser le flux
        feed = feedparser.parse(response.content)

        if feed.bozo and not feed.entries:
            return False, {}, f"Flux RSS invalide : {feed.bozo_exception}"

        if not feed.feed:
            return False, {}, "Aucun flux RSS trouvé à cette URL"

        feed_info = {
            "title": feed.feed.get("title", ""),
            "description": feed.feed.get("description", feed.feed.get("subtitle", "")),
            "link": feed.feed.get("link", ""),
            "favicon_url": _extract_favicon(feed.feed.get("link", url)),
            "entries_count": len(feed.entries),
        }

        return True, feed_info, ""

    except Timeout:
        return False, {}, "Délai d'attente dépassé lors de la connexion au flux"
    except RequestException as e:
        return False, {}, f"Erreur de connexion : {str(e)}"
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la validation de {url}: {e}")
        return False, {}, f"Erreur inattendue : {str(e)}"


def fetch_feed_info(url: str) -> Dict[str, Any]:
    """Récupère les métadonnées d'un flux RSS."""
    _, info, _ = validate_rss_url(url)
    return info


def fetch_feed_articles(feed_url: str, last_fetched: Optional[datetime] = None) -> Tuple[List[Dict], str]:
    """
    Collecte les nouveaux articles d'un flux RSS.

    Args:
        feed_url: URL du flux RSS
        last_fetched: Date de la dernière collecte (pour filtrer les nouveaux articles)

    Returns:
        Tuple (articles_list, error_message)
    """
    try:
        headers = {"User-Agent": USER_AGENT}

        # Utiliser ETag/Last-Modified si disponible
        response = requests.get(feed_url, timeout=REQUEST_TIMEOUT, headers=headers,
                                allow_redirects=True)
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        if feed.bozo and not feed.entries:
            error = str(feed.bozo_exception) if hasattr(feed, "bozo_exception") else "Flux invalide"
            return [], f"Flux invalide : {error}"

        # Normaliser last_fetched une seule fois
        if last_fetched and last_fetched.tzinfo is None:
            last_fetched = last_fetched.replace(tzinfo=timezone.utc)

        articles = []
        for entry in feed.entries:
            # Extraire la date de publication
            pub_date = _parse_entry_date(entry)

            # Filtrer les anciens articles sur la date de PUBLICATION.
            # On utilise une marge de 25h (au lieu de last_fetched strict) pour
            # ne pas rater les articles dont la date de publication est légèrement
            # antérieure à la dernière collecte (décalages d'horloge, corrections
            # de date, etc.). La déduplication par hash dans fetch_all_feeds
            # garantit qu'on n'insère pas de doublons.
            if last_fetched and pub_date:
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                from datetime import timedelta
                cutoff = last_fetched - timedelta(hours=25)
                if pub_date < cutoff:
                    continue

            # Extraire le contenu
            content = _extract_content(entry)
            url = entry.get("link", "")
            title = entry.get("title", "Sans titre")

            if not url:
                continue

            article = {
                "title": title[:1024],
                "url": url[:2048],
                "content": content[:10000] if content else None,
                "author": entry.get("author", ""),
                "published_at": pub_date,
                "hash": _compute_article_hash(url, title),
            }
            articles.append(article)

        logger.debug(f"Collecté {len(articles)} articles depuis {feed_url}")
        return articles, ""

    except Timeout:
        return [], "Délai d'attente dépassé"
    except RequestException as e:
        return [], f"Erreur réseau : {str(e)}"
    except Exception as e:
        logger.error(f"Erreur lors de la collecte de {feed_url}: {e}")
        return [], f"Erreur inattendue : {str(e)}"


def _parse_entry_date(entry) -> Optional[datetime]:
    """Extrait et normalise la date de publication d'une entrée RSS.

    feedparser retourne les dates en tuples UTC (time.struct_time).
    Il faut utiliser calendar.timegm() (interprète le tuple comme UTC)
    et NON time.mktime() (qui l'interprète comme heure locale, ce qui
    décale les dates de +1h ou +2h selon le fuseau horaire du système).
    """
    import calendar

    for date_field in ("published_parsed", "updated_parsed", "created_parsed"):
        date_tuple = entry.get(date_field)
        if date_tuple:
            try:
                # calendar.timegm : tuple UTC → timestamp UTC (pas de décalage TZ)
                ts = calendar.timegm(date_tuple)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _extract_content(entry) -> Optional[str]:
    """Extrait le contenu textuel d'une entrée RSS."""
    import bleach

    # Priorité : content > summary > description
    content = None

    if hasattr(entry, "content") and entry.content:
        content = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        content = entry.summary
    elif hasattr(entry, "description"):
        content = entry.description

    if content:
        # Nettoyer le HTML
        allowed_tags = ["p", "br", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3"]
        content = bleach.clean(content, tags=allowed_tags, strip=True)
        # Supprimer les espaces excessifs
        content = " ".join(content.split())

    return content


def _extract_favicon(site_url: str) -> Optional[str]:
    """Tente d'extraire l'URL du favicon d'un site."""
    if not site_url:
        return None
    try:
        parsed = urlparse(site_url)
        return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    except Exception:
        return None


def _compute_article_hash(url: str, title: str) -> str:
    """Calcule un hash unique pour un article."""
    content = f"{url}|{title}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()
