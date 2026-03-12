"""
Service d'envoi d'emails.
Supporte SMTP (smtplib/Flask-Mail) et SendGrid.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional
from datetime import date

logger = logging.getLogger(__name__)


def _get_config():
    """Récupère la configuration email depuis Flask."""
    from flask import current_app
    return current_app.config


def send_email(
    to_emails: List[str],
    subject: str,
    html_body: str,
    text_body: Optional[str] = None
) -> bool:
    """
    Envoie un email via le provider configuré (SMTP ou SendGrid).

    Returns:
        True si l'envoi a réussi, False sinon.
    """
    config = _get_config()
    provider = config.get("EMAIL_PROVIDER", "smtp")

    if provider == "sendgrid":
        return _send_via_sendgrid(to_emails, subject, html_body, text_body, config)
    else:
        return _send_via_smtp(to_emails, subject, html_body, text_body, config)


def _send_via_smtp(
    to_emails: List[str],
    subject: str,
    html_body: str,
    text_body: Optional[str],
    config: dict
) -> bool:
    """Envoi via SMTP avec smtplib."""
    try:
        smtp_host = config.get("MAIL_SERVER", "smtp.gmail.com")
        smtp_port = int(config.get("MAIL_PORT", 587))
        smtp_user = config.get("MAIL_USERNAME", "")
        smtp_password = config.get("MAIL_PASSWORD", "")
        from_email = config.get("MAIL_DEFAULT_SENDER", smtp_user)
        use_tls = config.get("MAIL_USE_TLS", True)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = ", ".join(to_emails)

        if text_body:
            msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_email, to_emails, msg.as_string())

        logger.info(f"Email envoyé via SMTP à : {', '.join(to_emails)}")
        return True

    except Exception as e:
        logger.error(f"Erreur SMTP lors de l'envoi à {to_emails}: {e}")
        return False


def _send_via_sendgrid(
    to_emails: List[str],
    subject: str,
    html_body: str,
    text_body: Optional[str],
    config: dict
) -> bool:
    """Envoi via SendGrid API."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, To

        sg = SendGridAPIClient(api_key=config.get("SENDGRID_API_KEY", ""))
        from_email = config.get("MAIL_DEFAULT_SENDER", "noreply@rssveille.local")

        message = Mail(
            from_email=from_email,
            to_emails=[To(email) for email in to_emails],
            subject=subject,
            html_content=html_body,
            plain_text_content=text_body or "",
        )

        response = sg.send(message)
        logger.info(f"Email envoyé via SendGrid à : {', '.join(to_emails)} "
                    f"(status: {response.status_code})")
        return response.status_code in (200, 202)

    except Exception as e:
        logger.error(f"Erreur SendGrid lors de l'envoi à {to_emails}: {e}")
        return False


# ─── Emails transactionnels ───────────────────────────────────────────────

def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    """Envoie l'email de réinitialisation de mot de passe."""
    subject = "Réinitialisation de votre mot de passe — RSS Veille"
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #3B82F6;">Réinitialisation de mot de passe</h2>
        <p>Vous avez demandé la réinitialisation de votre mot de passe sur RSS Veille.</p>
        <p>Cliquez sur le bouton ci-dessous pour définir un nouveau mot de passe :</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}" style="background-color: #3B82F6; color: white;
               padding: 12px 24px; text-decoration: none; border-radius: 6px;
               font-weight: bold;">Réinitialiser mon mot de passe</a>
        </p>
        <p style="color: #6B7280; font-size: 14px;">
            Ce lien est valable 1 heure. Si vous n'avez pas fait cette demande, ignorez cet email.
        </p>
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 20px 0;">
        <p style="color: #9CA3AF; font-size: 12px;">RSS Veille — Application de veille intelligente</p>
    </body></html>
    """
    return send_email([to_email], subject, html_body)


def send_invitation_email(to_email: str, invite_url: str, invited_by: str) -> bool:
    """Envoie l'email d'invitation à rejoindre l'application."""
    subject = "Invitation à rejoindre RSS Veille"
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #3B82F6;">Vous êtes invité(e) sur RSS Veille</h2>
        <p><strong>{invited_by}</strong> vous invite à rejoindre RSS Veille,
           l'application de veille RSS intelligente avec synthèses IA.</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{invite_url}" style="background-color: #10B981; color: white;
               padding: 12px 24px; text-decoration: none; border-radius: 6px;
               font-weight: bold;">Créer mon compte</a>
        </p>
        <p style="color: #6B7280; font-size: 14px;">
            Ce lien d'invitation est valable 7 jours.
        </p>
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 20px 0;">
        <p style="color: #9CA3AF; font-size: 12px;">RSS Veille — Application de veille intelligente</p>
    </body></html>
    """
    return send_email([to_email], subject, html_body)


def send_subscription_confirmation(to_email: str, owner_email: str) -> bool:
    """Envoie une confirmation d'abonnement aux synthèses."""
    subject = f"Abonnement aux synthèses de {owner_email} — RSS Veille"
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #3B82F6;">Abonnement confirmé</h2>
        <p>Vous êtes maintenant abonné(e) aux synthèses de veille de <strong>{owner_email}</strong>.</p>
        <p>Vous recevrez les synthèses quotidiennes et/ou hebdomadaires selon les préférences configurées.</p>
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 20px 0;">
        <p style="color: #9CA3AF; font-size: 12px;">RSS Veille — Application de veille intelligente</p>
    </body></html>
    """
    return send_email([to_email], subject, html_body)


def send_feed_dead_notification(to_email: str, feed_name: str, feed_url: str) -> bool:
    """Notifie l'utilisateur qu'un flux est mort."""
    subject = f"Flux RSS inactif : {feed_name} — RSS Veille"
    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #EF4444;">Flux RSS inaccessible</h2>
        <p>Le flux RSS <strong>{feed_name}</strong> est inaccessible depuis plusieurs tentatives.</p>
        <p style="color: #6B7280;">URL : <code>{feed_url}</code></p>
        <p>Le flux a été automatiquement désactivé. Vous pouvez le réactiver depuis votre
           <a href="#" style="color: #3B82F6;">tableau de bord</a> une fois le problème résolu.</p>
        <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 20px 0;">
        <p style="color: #9CA3AF; font-size: 12px;">RSS Veille — Application de veille intelligente</p>
    </body></html>
    """
    return send_email([to_email], subject, html_body)


def send_daily_synthesis_email(
    to_emails: List[str],
    user_name: str,
    syntheses_by_category: List[dict],
    synthesis_date: date
) -> bool:
    """
    Envoie l'email de synthèse quotidienne.

    Args:
        to_emails: Liste des destinataires
        user_name: Nom/email de l'utilisateur
        syntheses_by_category: Liste de dicts {category_name, content, articles_count}
        synthesis_date: Date de la synthèse
    """
    date_str = synthesis_date.strftime("%A %d %B %Y")
    subject = f"Synthèse RSS du {date_str}"

    # Construire le corps HTML
    categories_html = ""
    for item in syntheses_by_category:
        content_html = item["content"].replace("\n", "<br>")
        categories_html += f"""
        <div style="margin-bottom: 30px; padding: 20px; background: #F9FAFB;
                    border-radius: 8px; border-left: 4px solid #3B82F6;">
            <h3 style="color: #1F2937; margin-top: 0;">{item['category_name']}</h3>
            <p style="color: #6B7280; font-size: 13px; margin-bottom: 15px;">
                {item.get('articles_count', 0)} article(s) analysé(s)
            </p>
            <div style="color: #374151; line-height: 1.6;">{content_html}</div>
        </div>
        """

    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;
                       color: #1F2937;">
        <div style="background: #3B82F6; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 22px;">
                📰 Synthèse RSS — {date_str}
            </h1>
        </div>
        <div style="padding: 20px; background: white; border: 1px solid #E5E7EB;
                    border-top: none; border-radius: 0 0 8px 8px;">
            <p>Bonjour,</p>
            <p>Voici votre synthèse de veille RSS du jour.</p>
            {categories_html}
            <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 20px 0;">
            <p style="color: #9CA3AF; font-size: 12px;">
                RSS Veille — Vous recevez cet email car vous êtes abonné aux synthèses quotidiennes.
            </p>
        </div>
    </body></html>
    """

    return send_email(to_emails, subject, html_body)


def send_weekly_synthesis_email(
    to_emails: List[str],
    syntheses_by_category: List[dict],
    week_start: date,
    week_end: date
) -> bool:
    """
    Envoie l'email de synthèse hebdomadaire avec draft LinkedIn.

    Args:
        to_emails: Liste des destinataires
        syntheses_by_category: Liste de dicts {category_name, content, key_facts, trends,
                                                draft_linkedin, articles_count}
        week_start: Début de la semaine
        week_end: Fin de la semaine
    """
    period = f"du {week_start.strftime('%d/%m')} au {week_end.strftime('%d/%m/%Y')}"
    subject = f"Synthèse hebdomadaire RSS — Semaine {period}"

    categories_html = ""
    for item in syntheses_by_category:
        linkedin_html = ""
        if item.get("draft_linkedin"):
            linkedin_content = item["draft_linkedin"].replace("\n", "<br>")
            linkedin_html = f"""
            <div style="margin-top: 20px; padding: 15px; background: #EFF6FF;
                        border-radius: 6px; border: 1px solid #BFDBFE;">
                <h4 style="color: #1D4ED8; margin-top: 0;">💼 Draft Post LinkedIn</h4>
                <div style="color: #374151; line-height: 1.6; white-space: pre-line;">
                    {linkedin_content}
                </div>
            </div>
            """

        key_facts_html = ""
        if item.get("key_facts"):
            key_facts_content = item["key_facts"].replace("\n", "<br>")
            key_facts_html = f"""
            <div style="margin-top: 15px;">
                <h4 style="color: #1F2937;">📌 Faits marquants</h4>
                <div style="color: #374151; line-height: 1.6;">{key_facts_content}</div>
            </div>
            """

        trends_html = ""
        if item.get("trends"):
            trends_content = item["trends"].replace("\n", "<br>")
            trends_html = f"""
            <div style="margin-top: 15px;">
                <h4 style="color: #1F2937;">📈 Tendances observées</h4>
                <div style="color: #374151; line-height: 1.6;">{trends_content}</div>
            </div>
            """

        content_html = item.get("content", "").replace("\n", "<br>")

        categories_html += f"""
        <div style="margin-bottom: 40px; padding: 20px; background: #F9FAFB;
                    border-radius: 8px; border-left: 4px solid #8B5CF6;">
            <h3 style="color: #1F2937; margin-top: 0;">{item['category_name']}</h3>
            <p style="color: #6B7280; font-size: 13px; margin-bottom: 15px;">
                {item.get('articles_count', 0)} article(s) analysé(s) cette semaine
            </p>
            <div style="color: #374151; line-height: 1.6;">{content_html}</div>
            {key_facts_html}
            {trends_html}
            {linkedin_html}
        </div>
        """

    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;
                       color: #1F2937;">
        <div style="background: #8B5CF6; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 22px;">
                📊 Synthèse Hebdomadaire — {period}
            </h1>
        </div>
        <div style="padding: 20px; background: white; border: 1px solid #E5E7EB;
                    border-top: none; border-radius: 0 0 8px 8px;">
            <p>Bonjour,</p>
            <p>Voici votre synthèse de veille RSS de la semaine, avec les drafts de posts
               LinkedIn prêts à utiliser.</p>
            {categories_html}
            <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 20px 0;">
            <p style="color: #9CA3AF; font-size: 12px;">
                RSS Veille — Vous recevez cet email car vous êtes abonné aux synthèses hebdomadaires.
            </p>
        </div>
    </body></html>
    """

    return send_email(to_emails, subject, html_body)
