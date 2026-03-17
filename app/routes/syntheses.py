"""
Routes de consultation des synthèses IA.
"""
import logging
from flask import Blueprint, render_template, request, abort, redirect, url_for, flash
from flask_login import login_required, current_user

from main import db
from models.synthesis import Synthesis
from models.category import Category

logger = logging.getLogger(__name__)
syntheses_bp = Blueprint("syntheses", __name__, url_prefix="/syntheses")


@syntheses_bp.route("/")
@login_required
def index():
    """Historique des synthèses quotidiennes et hebdomadaires."""
    page = request.args.get("page", 1, type=int)
    type_filter = request.args.get("type")  # daily | weekly
    category_id = request.args.get("category", type=int)

    query = Synthesis.query.filter_by(user_id=current_user.id)

    if type_filter in (Synthesis.TYPE_DAILY, Synthesis.TYPE_WEEKLY):
        query = query.filter_by(type=type_filter)

    if category_id:
        query = query.filter_by(category_id=category_id)

    syntheses = (
        query
        .order_by(Synthesis.generated_at.desc())
        .paginate(page=page, per_page=10, error_out=False)
    )

    categories = Category.query.filter_by(user_id=current_user.id, active=True).all()

    return render_template(
        "syntheses/index.html",
        syntheses=syntheses,
        categories=categories,
        type_filter=type_filter,
        selected_category=category_id,
    )


@syntheses_bp.route("/<int:synthesis_id>")
@login_required
def detail(synthesis_id: int):
    """Détail d'une synthèse."""
    synthesis = Synthesis.query.filter_by(
        id=synthesis_id, user_id=current_user.id
    ).first_or_404()

    return render_template("syntheses/detail.html", synthesis=synthesis)


@syntheses_bp.route("/<int:synthesis_id>/delete", methods=["POST"])
@login_required
def delete(synthesis_id: int):
    """Suppression d'une synthèse."""
    synthesis = Synthesis.query.filter_by(
        id=synthesis_id, user_id=current_user.id
    ).first_or_404()

    label = f"{synthesis.type} — {synthesis.period_start.strftime('%d/%m/%Y') if synthesis.period_start else synthesis.generated_at.strftime('%d/%m/%Y')}"
    db.session.delete(synthesis)
    db.session.commit()
    logger.info(f"Synthèse #{synthesis_id} supprimée par {current_user.email} ({label})")
    flash(f"Synthèse supprimée : {label}", "success")
    return redirect(url_for("syntheses.index"))
