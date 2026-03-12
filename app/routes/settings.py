"""
Routes des préférences et paramètres utilisateur.
"""
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer

from main import db
from models.user import User
from models.category import Category
from models.subscription import Subscription
from services.email_sender import send_subscription_confirmation

logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.route("/")
@login_required
def index():
    """Page des préférences."""
    categories = Category.query.filter_by(user_id=current_user.id, active=True).all()
    subscriptions = Subscription.query.filter_by(owner_user_id=current_user.id).all()
    return render_template("settings/index.html", categories=categories,
                           subscriptions=subscriptions)


@settings_bp.route("/preferences", methods=["POST"])
@login_required
def update_preferences():
    """Mise à jour des préférences email."""
    prefs = current_user.preferences

    prefs["receive_daily"] = request.form.get("receive_daily") == "on"
    prefs["receive_weekly"] = request.form.get("receive_weekly") == "on"
    prefs["email_hour"] = int(request.form.get("email_hour", 7))
    prefs["timezone"] = request.form.get("timezone", "Europe/Paris")

    # Catégories sélectionnées pour les emails
    daily_cats = request.form.getlist("daily_categories")
    weekly_cats = request.form.getlist("weekly_categories")
    prefs["daily_categories"] = [int(c) for c in daily_cats if c.isdigit()]
    prefs["weekly_categories"] = [int(c) for c in weekly_cats if c.isdigit()]

    current_user.preferences = prefs
    db.session.commit()
    flash("Préférences mises à jour.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    """Changement de mot de passe."""
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash("Mot de passe actuel incorrect.", "danger")
        return redirect(url_for("settings.index"))

    if len(new_password) < 8:
        flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
        return redirect(url_for("settings.index"))

    if new_password != confirm_password:
        flash("Les mots de passe ne correspondent pas.", "danger")
        return redirect(url_for("settings.index"))

    current_user.set_password(new_password)
    db.session.commit()
    flash("Mot de passe modifié avec succès.", "success")
    logger.info(f"Mot de passe changé pour : {current_user.email}")
    return redirect(url_for("settings.index"))


@settings_bp.route("/subscriptions/add", methods=["POST"])
@login_required
def add_subscription():
    """Ajout d'un abonné aux synthèses."""
    email = request.form.get("email", "").strip().lower()

    if not email:
        flash("L'email est obligatoire.", "danger")
        return redirect(url_for("settings.index"))

    existing = Subscription.query.filter_by(
        owner_user_id=current_user.id, subscriber_email=email
    ).first()
    if existing:
        flash("Cet email est déjà abonné.", "warning")
        return redirect(url_for("settings.index"))

    sub = Subscription(
        owner_user_id=current_user.id,
        subscriber_email=email,
        receive_daily=request.form.get("receive_daily") == "on",
        receive_weekly=request.form.get("receive_weekly") == "on",
    )
    db.session.add(sub)
    db.session.commit()

    flash(f"Abonné {email} ajouté.", "success")
    logger.info(f"Abonné ajouté : {email} pour user={current_user.id}")
    return redirect(url_for("settings.index"))


@settings_bp.route("/subscriptions/<int:sub_id>/delete", methods=["POST"])
@login_required
def delete_subscription(sub_id: int):
    """Suppression d'un abonné."""
    sub = Subscription.query.filter_by(
        id=sub_id, owner_user_id=current_user.id
    ).first_or_404()
    email = sub.subscriber_email
    db.session.delete(sub)
    db.session.commit()
    flash(f"Abonné {email} supprimé.", "success")
    return redirect(url_for("settings.index"))
