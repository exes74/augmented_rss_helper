"""
Routes d'administration (rôle Admin uniquement).
"""
import logging
from functools import wraps
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, abort, current_app)
from flask_login import login_required, current_user
from itsdangerous import URLSafeTimedSerializer

from main import db
from models.user import User
from models.feed import Feed
from services.email_sender import send_invitation_email

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    """Décorateur : accès réservé aux administrateurs."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route("/")
@login_required
@admin_required
def index():
    """Tableau de bord d'administration."""
    users = User.query.order_by(User.created_at.desc()).all()
    stats = {
        "total_users": User.query.count(),
        "active_users": User.query.filter_by(is_active=True).count(),
        "total_feeds": Feed.query.count(),
        "dead_feeds": Feed.query.filter_by(status="dead").count(),
    }
    return render_template("admin/index.html", users=users, stats=stats)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id: int):
    """Active ou désactive un utilisateur."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Vous ne pouvez pas désactiver votre propre compte.", "danger")
        return redirect(url_for("admin.index"))

    user.is_active = not user.is_active
    db.session.commit()
    state = "activé" if user.is_active else "désactivé"
    flash(f"Utilisateur {user.email} {state}.", "success")
    logger.info(f"Utilisateur {user.email} {state} par admin={current_user.email}")
    return redirect(url_for("admin.index"))


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@login_required
@admin_required
def change_role(user_id: int):
    """Change le rôle d'un utilisateur."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Vous ne pouvez pas modifier votre propre rôle.", "danger")
        return redirect(url_for("admin.index"))

    new_role = request.form.get("role")
    if new_role not in ("admin", "user"):
        flash("Rôle invalide.", "danger")
        return redirect(url_for("admin.index"))

    user.role = new_role
    db.session.commit()
    flash(f"Rôle de {user.email} changé en « {new_role} ».", "success")
    return redirect(url_for("admin.index"))


@admin_bp.route("/invite", methods=["GET", "POST"])
@login_required
@admin_required
def invite():
    """Invitation d'un nouvel utilisateur par email."""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        if not email:
            flash("L'email est obligatoire.", "danger")
            return render_template("admin/invite.html")

        # Vérifier si l'email est déjà utilisé
        if User.query.filter_by(email=email).first():
            flash(f"L'email {email} est déjà enregistré.", "warning")
            return render_template("admin/invite.html")

        # Générer le token d'invitation
        s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        token = s.dumps(
            {"email": email, "invited_by": current_user.id},
            salt="invite"
        )
        invite_url = url_for("auth.register", token=token, _external=True)

        try:
            send_invitation_email(email, invite_url, current_user.email)
            flash(f"Invitation envoyée à {email}.", "success")
            logger.info(f"Invitation envoyée à {email} par admin={current_user.email}")
        except Exception as e:
            logger.error(f"Erreur envoi invitation : {e}")
            flash(f"Erreur lors de l'envoi de l'invitation : {str(e)}", "danger")

        return redirect(url_for("admin.index"))

    return render_template("admin/invite.html")


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id: int):
    """Suppression d'un utilisateur."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Vous ne pouvez pas supprimer votre propre compte.", "danger")
        return redirect(url_for("admin.index"))

    email = user.email
    db.session.delete(user)
    db.session.commit()
    flash(f"Utilisateur {email} supprimé.", "success")
    logger.info(f"Utilisateur {email} supprimé par admin={current_user.email}")
    return redirect(url_for("admin.index"))
