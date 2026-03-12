"""
Routes de gestion des catégories.
"""
import logging
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app)
from flask_login import login_required, current_user

from main import db
from models.category import Category

logger = logging.getLogger(__name__)
categories_bp = Blueprint("categories", __name__, url_prefix="/categories")


@categories_bp.route("/")
@login_required
def index():
    """Liste des catégories de l'utilisateur."""
    categories = (
        Category.query
        .filter_by(user_id=current_user.id)
        .order_by(Category.name.asc())
        .all()
    )
    return render_template("categories/index.html", categories=categories)


@categories_bp.route("/add", methods=["POST"])
@login_required
def add():
    """Ajout d'une nouvelle catégorie."""
    max_cats = current_app.config.get("MAX_CATEGORIES_PER_USER", 20)
    current_count = Category.query.filter_by(user_id=current_user.id).count()

    if current_count >= max_cats:
        flash(f"Limite de {max_cats} catégories atteinte.", "warning")
        return redirect(url_for("categories.index"))

    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#3B82F6").strip()

    if not name:
        flash("Le nom de la catégorie est obligatoire.", "danger")
        return redirect(url_for("categories.index"))

    # Vérifier l'unicité
    existing = Category.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        flash(f"La catégorie « {name} » existe déjà.", "warning")
        return redirect(url_for("categories.index"))

    category = Category(user_id=current_user.id, name=name, color=color)
    db.session.add(category)
    db.session.commit()

    flash(f"Catégorie « {name} » créée.", "success")
    logger.info(f"Catégorie créée : {name} par user={current_user.id}")
    return redirect(url_for("categories.index"))


@categories_bp.route("/<int:cat_id>/edit", methods=["POST"])
@login_required
def edit(cat_id: int):
    """Modification d'une catégorie."""
    category = Category.query.filter_by(id=cat_id, user_id=current_user.id).first_or_404()

    name = request.form.get("name", "").strip()
    color = request.form.get("color", category.color).strip()

    if name and name != category.name:
        existing = Category.query.filter_by(user_id=current_user.id, name=name).first()
        if existing:
            flash(f"La catégorie « {name} » existe déjà.", "warning")
            return redirect(url_for("categories.index"))
        category.name = name

    category.color = color
    db.session.commit()
    flash("Catégorie mise à jour.", "success")
    return redirect(url_for("categories.index"))


@categories_bp.route("/<int:cat_id>/toggle", methods=["POST"])
@login_required
def toggle(cat_id: int):
    """Active ou désactive une catégorie."""
    category = Category.query.filter_by(id=cat_id, user_id=current_user.id).first_or_404()
    category.active = not category.active
    db.session.commit()
    state = "activée" if category.active else "désactivée"
    flash(f"Catégorie « {category.name} » {state}.", "success")
    return redirect(url_for("categories.index"))


@categories_bp.route("/<int:cat_id>/delete", methods=["POST"])
@login_required
def delete(cat_id: int):
    """Suppression d'une catégorie (et de ses flux associés)."""
    category = Category.query.filter_by(id=cat_id, user_id=current_user.id).first_or_404()
    name = category.name
    db.session.delete(category)
    db.session.commit()
    flash(f"Catégorie « {name} » supprimée.", "success")
    logger.info(f"Catégorie supprimée : {cat_id} par user={current_user.id}")
    return redirect(url_for("categories.index"))
