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

# Noms des jours et mois en français
_JOURS_FR = [
    "lundi", "mardi", "mercredi", "jeudi",
    "vendredi", "samedi", "dimanche"
]
_MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]


def _date_fr(d: date) -> str:
    """Retourne une date formatée en français, ex : 'lundi 16 mars 2026'."""
    jour = _JOURS_FR[d.weekday()]
    mois = _MOIS_FR[d.month - 1]
    return f"{jour} {d.day} {mois} {d.year}"


def _date_short_fr(d: date) -> str:
    """Retourne une date courte en français, ex : '16 mars 2026'."""
    mois = _MOIS_FR[d.month - 1]
    return f"{d.day} {mois} {d.year}"

logger = logging.getLogger(__name__)


def _markdown_to_html(text: str) -> str:
    """
    Convertit le Markdown généré par le LLM en HTML propre pour les emails.
    Utilise la librairie `markdown` si disponible, sinon un fallback regex léger.
    """
    try:
        import markdown as md_lib
        # Extensions : tables, nl2br (newlines -> <br>), sane_lists
        html = md_lib.markdown(
            text,
            extensions=["nl2br", "sane_lists"],
        )
        return html
    except ImportError:
        pass

    # Fallback manuel si la lib n'est pas disponible
    import re
    lines = text.split("\n")
    result = []
    in_ul = False

    for line in lines:
        # Titres ## et ###
        if line.startswith("### "):
            if in_ul:
                result.append("</ul>"); in_ul = False
            result.append(f"<h4 style='color:#1F2937;margin:12px 0 4px'>{line[4:].strip()}</h4>")
            continue
        if line.startswith("## "):
            if in_ul:
                result.append("</ul>"); in_ul = False
            result.append(f"<h3 style='color:#1F2937;margin:14px 0 6px'>{line[3:].strip()}</h3>")
            continue
        if line.startswith("# "):
            if in_ul:
                result.append("</ul>"); in_ul = False
            result.append(f"<h2 style='color:#1F2937;margin:16px 0 8px'>{line[2:].strip()}</h2>")
            continue

        # Listes (• ou - ou *)
        if re.match(r'^[\u2022\-\*] ', line):
            if not in_ul:
                result.append("<ul style='margin:6px 0;padding-left:20px'>")
                in_ul = True
            item_text = line[2:].strip()
            # Gras inline **texte**
            item_text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', item_text)
            result.append(f"<li style='margin-bottom:4px'>{item_text}</li>")
            continue

        # Ligne vide
        if not line.strip():
            if in_ul:
                result.append("</ul>"); in_ul = False
            result.append("")
            continue

        # Paragraphe normal
        if in_ul:
            result.append("</ul>"); in_ul = False
        # Gras inline **texte**
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        result.append(f"<p style='margin:6px 0'>{line}</p>")

    if in_ul:
        result.append("</ul>")

    return "\n".join(result)


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

        # Encoder le sujet en RFC 2047 (UTF-8) pour les caractères non-ASCII (emojis, accents)
        from email.header import Header
        msg.replace_header("Subject", Header(subject, charset="utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            # Utiliser send_message au lieu de sendmail+as_string pour éviter
            # l'encodage ASCII strict qui bloque les emojis et accents
            server.send_message(msg)

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
        syntheses_by_category: Liste de dicts {category_name, content, articles_count, articles}
        synthesis_date: Date de la synthèse
    """
    date_str = _date_fr(synthesis_date)
    date_short = synthesis_date.strftime("%d/%m/%Y")

    # Sujet : une ligne par catégorie si une seule, sinon générique
    if len(syntheses_by_category) == 1:
        cat_name = syntheses_by_category[0]["category_name"]
        subject = f"Synthèse {cat_name} — {date_short}"
    else:
        subject = f"Synthèse RSS du {date_str}"

    # Construire le corps HTML des synthèses
    categories_html = ""
    for item in syntheses_by_category:
        # Sujet/titre par catégorie
        cat_date_title = f"Synthèse {item['category_name']} — {date_short}"
        # Convertir le Markdown généré par le LLM en HTML propre
        content_html = _markdown_to_html(item["content"])
        categories_html += f"""
        <div style="margin-bottom: 30px; padding: 20px; background: #F9FAFB;
                    border-radius: 8px; border-left: 4px solid #3B82F6;">
            <h3 style="color: #1F2937; margin-top: 0;">{cat_date_title}</h3>
            <p style="color: #6B7280; font-size: 13px; margin-bottom: 15px;">
                {item.get('articles_count', 0)} article(s) analysé(s)
            </p>
            <div style="color: #374151; line-height: 1.6; font-size: 14px;">{content_html}</div>
        </div>
        """

    # Construire la section sources
    sources_html = ""
    all_articles = []
    for item in syntheses_by_category:
        for article in item.get("articles", []):
            all_articles.append({
                "title": article.get("title", "Sans titre"),
                "url": article.get("url", ""),
                "feed_name": article.get("feed_name", ""),
                "category": item["category_name"],
                "published_at": article.get("published_at", ""),
            })

    if all_articles:
        sources_rows = ""
        for art in all_articles:
            pub = ""
            if art["published_at"]:
                try:
                    if hasattr(art["published_at"], "strftime"):
                        pub = art["published_at"].strftime("%d/%m")
                    else:
                        pub = str(art["published_at"])[:10]
                except Exception:
                    pass
            url = art["url"]
            title = art["title"]
            feed = art["feed_name"]
            cat = art["category"]
            sources_rows += f"""
            <tr>
                <td style="padding: 3px 8px; color: #6B7280;">{pub}</td>
                <td style="padding: 3px 8px; color: #6B7280;">{cat}</td>
                <td style="padding: 3px 8px; color: #6B7280;">{feed}</td>
                <td style="padding: 3px 8px;">
                    <a href="{url}" style="color: #3B82F6; text-decoration: none;">{title}</a>
                </td>
            </tr>"""

        sources_html = f"""
        <div style="margin-top: 30px; padding: 15px; background: #F9FAFB;
                    border-radius: 8px; border: 1px solid #E5E7EB;">
            <h4 style="color: #9CA3AF; font-size: 12px; margin: 0 0 10px 0;
                       text-transform: uppercase; letter-spacing: 0.05em;">
                Sources ({len(all_articles)} articles consultés)
            </h4>
            <table style="width: 100%; border-collapse: collapse; font-size: 11px;">
                <thead>
                    <tr style="border-bottom: 1px solid #E5E7EB;">
                        <th style="padding: 3px 8px; text-align: left; color: #9CA3AF;
                                   font-weight: normal;">Date</th>
                        <th style="padding: 3px 8px; text-align: left; color: #9CA3AF;
                                   font-weight: normal;">Catégorie</th>
                        <th style="padding: 3px 8px; text-align: left; color: #9CA3AF;
                                   font-weight: normal;">Source</th>
                        <th style="padding: 3px 8px; text-align: left; color: #9CA3AF;
                                   font-weight: normal;">Article</th>
                    </tr>
                </thead>
                <tbody>
                    {sources_rows}
                </tbody>
            </table>
        </div>
        """

    html_body = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;
                       color: #1F2937;">
        <div style="background: #3B82F6; padding: 20px; border-radius: 8px 8px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 22px;">
                Synthèse RSS — {date_str.capitalize()}
            </h1>
        </div>
        <div style="padding: 20px; background: white; border: 1px solid #E5E7EB;
                    border-top: none; border-radius: 0 0 8px 8px;">
            <p>Bonjour,</p>
            <p>Voici votre synthèse de veille RSS du jour.</p>
            {categories_html}
            {sources_html}
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
        # ─── Section Synthèse ───
        content_html = _markdown_to_html(item.get("content", ""))

        # ─── Section Faits marquants ───
        key_facts_html = ""
        if item.get("key_facts"):
            key_facts_html = f"""
            <div style="margin-top: 20px; padding: 15px; background: #FFF7ED;
                        border-radius: 6px; border-left: 4px solid #F59E0B;">
                <h4 style="color: #92400E; margin-top: 0; font-size: 14px;
                           text-transform: uppercase; letter-spacing: 0.05em;">
                    Faits marquants de la semaine
                </h4>
                <div style="color: #374151; line-height: 1.7; font-size: 14px;">
                    {_markdown_to_html(item['key_facts'])}
                </div>
            </div>
            """

        # ─── Section Tendances ───
        trends_html = ""
        if item.get("trends"):
            trends_html = f"""
            <div style="margin-top: 20px; padding: 15px; background: #F0FDF4;
                        border-radius: 6px; border-left: 4px solid #10B981;">
                <h4 style="color: #065F46; margin-top: 0; font-size: 14px;
                           text-transform: uppercase; letter-spacing: 0.05em;">
                    Tendances observées
                </h4>
                <div style="color: #374151; line-height: 1.7; font-size: 14px;">
                    {_markdown_to_html(item['trends'])}
                </div>
            </div>
            """

        categories_html += f"""
        <div style="margin-bottom: 40px; padding: 20px; background: #F9FAFB;
                    border-radius: 8px; border-left: 4px solid #8B5CF6;">
            <h3 style="color: #1F2937; margin-top: 0; font-size: 18px;">{item['category_name']}</h3>
            <p style="color: #6B7280; font-size: 13px; margin-bottom: 15px;">
                Super-synthèse — {item.get('articles_count', 0)} article(s) analysé(s) cette semaine
            </p>
            <div style="color: #374151; line-height: 1.7; font-size: 14px;">{content_html}</div>
            {key_facts_html}
            {trends_html}
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
            <p>Voici votre synthèse de veille RSS de la semaine.</p>
            {categories_html}
            <hr style="border: none; border-top: 1px solid #E5E7EB; margin: 20px 0;">
            <p style="color: #9CA3AF; font-size: 12px;">
                RSS Veille — Vous recevez cet email car vous êtes abonné aux synthèses hebdomadaires.
            </p>
        </div>
    </body></html>
    """

    return send_email(to_emails, subject, html_body)
