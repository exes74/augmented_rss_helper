"""
Routes d'authentification : inscription, connexion, déconnexion,
réinitialisation de mot de passe, invitation.
"""
import logging
from datetime import datetime, timezone, timedelta
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app)
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from main import db
from models.user import User
from services.email_sender import send_password_reset_email, send_invitation_email

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)


def get_serializer() -> URLSafeTimedSerializer:
    """Retourne le sérialiseur pour les tokens sécurisés."""
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


# ─── Connexion ────────────────────────────────────────────────────────────
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=remember)
            user.update_last_login()
            logger.info(f"Connexion réussie : {email}")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard.index"))
        else:
            flash("Email ou mot de passe incorrect.", "danger")
            logger.warning(f"Tentative de connexion échouée : {email}")

    return render_template("auth/login.html")


# ─── Inscription ──────────────────────────────────────────────────────────
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    token = request.args.get("token")
    invited_email = None
    invited_by_id = None

    # Vérification du token d'invitation
    if token:
        try:
            s = get_serializer()
            data = s.loads(token, salt="invite", max_age=7 * 24 * 3600)
            invited_email = data.get("email")
            invited_by_id = data.get("invited_by")
        except (SignatureExpired, BadSignature):
            flash("Le lien d'invitation est invalide ou expiré.", "danger")
            return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        # Validations
        if len(password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "danger")
            return render_template("auth/register.html", invited_email=invited_email)

        if password != password_confirm:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return render_template("auth/register.html", invited_email=invited_email)

        if User.query.filter_by(email=email).first():
            flash("Cet email est déjà utilisé.", "danger")
            return render_template("auth/register.html", invited_email=invited_email)

        # Création de l'utilisateur
        user = User(
            email=email,
            role="user",
            is_verified=bool(invited_email),  # Vérifié si invitation
            invited_by=invited_by_id,
        )
        user.set_password(password)
        user.preferences = User._default_preferences()

        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Compte créé avec succès. Bienvenue !", "success")
        logger.info(f"Nouvel utilisateur créé : {email}")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html", invited_email=invited_email)


# ─── Déconnexion ──────────────────────────────────────────────────────────
@auth_bp.route("/logout")
@login_required
def logout():
    logger.info(f"Déconnexion : {current_user.email}")
    logout_user()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("auth.login"))


# ─── Mot de passe oublié ──────────────────────────────────────────────────
@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()

        if user:
            s = get_serializer()
            token = s.dumps({"user_id": user.id}, salt="reset-password")
            reset_url = url_for("auth.reset_password", token=token, _external=True)
            try:
                send_password_reset_email(user.email, reset_url)
                logger.info(f"Email de réinitialisation envoyé à : {email}")
            except Exception as e:
                logger.error(f"Erreur envoi email reset : {e}")

        # Message générique pour ne pas révéler si l'email existe
        flash("Si cet email existe, un lien de réinitialisation a été envoyé.", "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


# ─── Réinitialisation du mot de passe ────────────────────────────────────
@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    try:
        s = get_serializer()
        data = s.loads(token, salt="reset-password", max_age=3600)
        user_id = data.get("user_id")
    except (SignatureExpired, BadSignature):
        flash("Le lien de réinitialisation est invalide ou expiré.", "danger")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.get(user_id)
    if not user:
        flash("Utilisateur introuvable.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if len(password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "danger")
            return render_template("auth/reset_password.html", token=token)

        if password != password_confirm:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return render_template("auth/reset_password.html", token=token)

        user.set_password(password)
        db.session.commit()
        flash("Mot de passe réinitialisé avec succès.", "success")
        logger.info(f"Mot de passe réinitialisé pour : {user.email}")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
