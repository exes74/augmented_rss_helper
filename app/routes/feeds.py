"""
Routes de gestion des flux RSS.
"""
import logging
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify, current_app)
from flask_login import login_required, current_user

from main import db
from models.feed import Feed
from models.category import Category
from services.rss_fetcher import validate_rss_url, fetch_feed_info

logger = logging.getLogger(__name__)
feeds_bp = Blueprint("feeds", __name__, url_prefix="/feeds")


@feeds_bp.route("/")
@login_required
def index():
    """Liste de tous les flux RSS de l'utilisateur."""
    category_id = request.args.get("category", type=int)
    status_filter = request.args.get("status")

    query = Feed.query.filter_by(user_id=current_user.id)

    if category_id:
        query = query.filter_by(category_id=category_id)
    if status_filter:
        query = query.filter_by(status=status_filter)

    feeds = query.order_by(Feed.name.asc()).all()
    categories = Category.query.filter_by(user_id=current_user.id, active=True).all()

    return render_template("feeds/index.html", feeds=feeds, categories=categories,
                           selected_category=category_id, status_filter=status_filter)


@feeds_bp.route("/add", methods=["GET", "POST"])
@login_required
def add():
    """Formulaire d'ajout d'un flux RSS."""
    categories = Category.query.filter_by(user_id=current_user.id, active=True).all()

    # Vérifier la limite
    max_feeds = current_app.config.get("MAX_FEEDS_PER_USER", 100)
    current_count = Feed.query.filter_by(user_id=current_user.id).count()

    if current_count >= max_feeds:
        flash(f"Vous avez atteint la limite de {max_feeds} flux RSS.", "warning")
        return redirect(url_for("feeds.index"))

    if request.method == "POST":
        url = request.form.get("url", "").strip()
        category_id = request.form.get("category_id", type=int)
        custom_name = request.form.get("name", "").strip()

        if not url:
            flash("L'URL du flux RSS est obligatoire.", "danger")
            return render_template("feeds/add.html", categories=categories)

        # Vérifier si le flux existe déjà
        existing = Feed.query.filter_by(user_id=current_user.id, url=url).first()
        if existing:
            flash("Ce flux RSS est déjà dans votre liste.", "warning")
            return redirect(url_for("feeds.index"))

        # Valider l'URL RSS
        is_valid, feed_info, error_msg = validate_rss_url(url)
        if not is_valid:
            flash(f"URL RSS invalide : {error_msg}", "danger")
            return render_template("feeds/add.html", categories=categories)

        # Vérifier la catégorie
        if category_id:
            cat = Category.query.filter_by(id=category_id, user_id=current_user.id).first()
            if not cat:
                category_id = None

        feed = Feed(
            user_id=current_user.id,
            category_id=category_id,
            url=url,
            name=custom_name or feed_info.get("title", url),
            description=feed_info.get("description", ""),
            favicon_url=feed_info.get("favicon_url"),
            status=Feed.STATUS_ACTIVE,
        )
        db.session.add(feed)
        db.session.commit()

        flash(f"Flux RSS « {feed.display_name} » ajouté avec succès.", "success")
        logger.info(f"Flux ajouté : {url} par user={current_user.id}")
        return redirect(url_for("feeds.index"))

    return render_template("feeds/add.html", categories=categories)


@feeds_bp.route("/<int:feed_id>/toggle", methods=["POST"])
@login_required
def toggle(feed_id: int):
    """Active ou désactive un flux RSS."""
    feed = Feed.query.filter_by(id=feed_id, user_id=current_user.id).first_or_404()
    feed.active = not feed.active
    if feed.active and feed.status == Feed.STATUS_PAUSED:
        feed.status = Feed.STATUS_ACTIVE
    elif not feed.active and feed.status == Feed.STATUS_ACTIVE:
        feed.status = Feed.STATUS_PAUSED
    db.session.commit()
    state = "activé" if feed.active else "désactivé"
    flash(f"Flux « {feed.display_name} » {state}.", "success")
    return redirect(url_for("feeds.index"))


@feeds_bp.route("/<int:feed_id>/edit", methods=["GET", "POST"])
@login_required
def edit(feed_id: int):
    """Modification d'un flux RSS."""
    feed = Feed.query.filter_by(id=feed_id, user_id=current_user.id).first_or_404()
    categories = Category.query.filter_by(user_id=current_user.id, active=True).all()

    if request.method == "POST":
        feed.name = request.form.get("name", "").strip() or feed.name
        category_id = request.form.get("category_id", type=int)
        if category_id:
            cat = Category.query.filter_by(id=category_id, user_id=current_user.id).first()
            feed.category_id = cat.id if cat else feed.category_id
        db.session.commit()
        flash("Flux mis à jour.", "success")
        return redirect(url_for("feeds.index"))

    return render_template("feeds/edit.html", feed=feed, categories=categories)


@feeds_bp.route("/<int:feed_id>/delete", methods=["POST"])
@login_required
def delete(feed_id: int):
    """Suppression d'un flux RSS."""
    feed = Feed.query.filter_by(id=feed_id, user_id=current_user.id).first_or_404()
    name = feed.display_name
    db.session.delete(feed)
    db.session.commit()
    flash(f"Flux « {name} » supprimé.", "success")
    logger.info(f"Flux supprimé : {feed_id} par user={current_user.id}")
    return redirect(url_for("feeds.index"))


@feeds_bp.route("/<int:feed_id>/articles")
@login_required
def articles(feed_id: int):
    """Affiche les articles stockés en base pour un flux RSS donné."""
    from models.article import Article

    feed = Feed.query.filter_by(id=feed_id, user_id=current_user.id).first_or_404()

    page = request.args.get("page", 1, type=int)
    per_page = 50
    search = request.args.get("q", "").strip()

    query = Article.query.filter_by(feed_id=feed.id)
    if search:
        query = query.filter(
            db.or_(
                Article.title.ilike(f"%{search}%"),
                Article.content.ilike(f"%{search}%"),
            )
        )

    pagination = query.order_by(Article.published_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        "feeds/articles.html",
        feed=feed,
        articles=pagination.items,
        pagination=pagination,
        search=search,
    )


@feeds_bp.route("/validate", methods=["POST"])
@login_required
def validate():
    """Validation AJAX d'une URL RSS."""
    url = request.json.get("url", "").strip()
    if not url:
        return jsonify({"valid": False, "error": "URL manquante"})

    is_valid, feed_info, error_msg = validate_rss_url(url)
    if is_valid:
        return jsonify({"valid": True, "info": feed_info})
    return jsonify({"valid": False, "error": error_msg})
