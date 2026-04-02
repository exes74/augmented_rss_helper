"""
Routes d'administration pour la configuration des prompts LLM.
Permet de personnaliser les prompts de synthèses depuis l'interface admin.
"""
import logging
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify)
from flask_login import login_required, current_user

from main import db
from routes.admin import admin_required

logger = logging.getLogger(__name__)
admin_prompts_bp = Blueprint("admin_prompts", __name__, url_prefix="/admin/prompts")

# ─── Prompts par défaut (extraits de ai_synthesizer.py) ──────────────────────
# Ces valeurs sont affichées comme placeholder quand aucune config n'est en base.
# Elles doivent rester synchronisées avec ai_synthesizer.py.

DEFAULT_DAILY = """\
Tu es un expert en veille informationnelle. Analyse les articles suivants collectés le {date_str} dans la catégorie "{category_name}" et génère une synthèse structurée.

ARTICLES DU JOUR ({articles_count} articles) :
{articles_text}

CONSIGNES :
- Synthèse de 500 à 700 mots
- Style informatif et professionnel
- Identifier les 5-10 points clés en repérant les informations mises en valeur par plusieurs articles
- Identifier les 3-5 points clés concernant la France spécifiquement
- Extraire les 3 à 5 tendances clés observées en croisant les articles
- Citer les sources (noms des sites/médias)
- Utiliser des bullet points pour la lisibilité
- Langue : français
- Prendre en compte TOUS les articles fournis
- Ne mettre en gras QUE ce qui est entre les symboles "**"

FORMAT ATTENDU :
## Synthèse du {date_str} — {category_name}

**Résumé :** [4-5 phrases de résumé général]

**Points clés :**

• [Point 1 avec source]
• [Point 2 avec source]
• [Point 3 avec source]
• [Point 4 avec source]
• [Point 5 avec source]
...

**Et en France ?** 

• [Point 1 concernant la France spécifiquement avec source]
• [Point 2 concernant la France spécifiquement avec source]
• [Point 3 concernant la France spécifiquement avec source]
...

**Tendances observées :**
• [Tendance 1]
• [Tendance 2]
...\
"""

DEFAULT_WEEKLY = """\
Tu es un expert en veille informationnelle. \
Tu disposes des synthèses quotidiennes de la semaine {period} pour la catégorie "{category_name}".
Ta mission : produire une super-synthèse hebdomadaire à partir de ces synthèses.

SYNTHÈSES QUOTIDIENNES DE LA SEMAINE ({nb_days} jours, {total_articles} articles au total) :
{syntheses_text}

CONSIGNES GÉNÉRALES :
- Langue : français
- Style professionnel et analytique
- Citer les sources mentionnées dans les synthèses
- Ne pas simplement concaténer les synthèses : produire une analyse transversale

Génère une réponse structurée avec les 3 sections suivantes, séparées par des marqueurs :

===SYNTHESE===
[Super-synthèse de la semaine en 400-500 mots. Identifier les fils conducteurs, les événements majeurs, les évolutions du secteur. Aller au-delà de la simple liste des faits : proposer une lecture transversale.]

===FAITS_MARQUANTS===
[Liste des 5-7 faits marquants de la semaine, extraits des synthèses quotidiennes]
• [Fait 1 — date — source]
• [Fait 2 — date — source]
...

===TENDANCES===
[Liste des 3-5 tendances majeures observées sur la semaine]
• [Tendance 1 : explication]
• [Tendance 2 : explication]
...\
"""

DEFAULT_CYBERBRIEF = """\
Tu es un expert en cybersécurité, style analytique, légèrement impertinent.
Audience : professionnels cyber (RSSI, analystes, pentesters) avec quelques profils mixtes.

Tu reçois {nb_days} synthèses quotidiennes au format suivant :
- Résumé
- Points clés (bullets)
- Tendances observées

Voici les syntheses:

{syntheses_text}

═══ TÂCHE ═══

Produis une métasynthèse hebdomadaire DE 3000 CARACTERES MAXIMUM structurée comme suit :

---

[TITRE]
Sobre, factuel, légèrement impertinent.
Résume la semaine sans l'épuiser.
Pas de question. Pas d'exclamation. Pas de jeu de mots forcé.

⚡ Cyber Brief — Semaine du {week_start_str} au {week_end_str} : [LE TITRE TROUVE AU DESSUS]

[INTRO — formulée en 2 à 3 phrases digestes]
Ce que cette semaine dit du secteur, en une lecture transversale.
Pas un résumé des 7 jours. Une lecture.
1 donnée chiffrée si elle est disponible dans les synthèses.

[2-3 tendances, formulées en 1-2 phrases chacune]
Une tendance = un fil qui traverse plusieurs faits, pas la répétition d'un fait.
Formuler ce qui monte, ce qui bascule, ce qui se confirme.
Impertinence autorisée si le consensus du secteur mérite d'être challengé.

[Les faits marquants]

1. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

2. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

3. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

4. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

→ Critères de sélection des 4 faits :
- Impact réel ou potentiel sur les organisations
- Nouveauté (pas une énième variante d'une menace connue)
- Révélateur d'une tendance plus large
- Diversité : ne pas prendre 5 faits du même registre (ex : 5 vulnérabilités)
- Faits mentionnés dans plusieurs syntheses différentes

[Ce qu'on en pense - 2-3 phrases]
Pas de conclusion rassurante. Pas de morale.
Une perspective constructive : ce qui avance, ce qui protège mieux,
ce qui mérite d'être suivi la semaine prochaine.
Ton sobre. 1 ou 2 idées fortes.

#Cybersécurité #[HashtagNiche1] #[HashtagNiche2] #RSSI

═══ CONTRAINTES ═══

FOND :
- Croiser les {nb_days} synthèses, pas les additionner
- Les tendances doivent être transversales (au moins 2 synthèses différentes)
- 0 fait inventé ou extrapolé au-delà des sources

FORME — BUDGETS STRICTS :
- Titre : 1 ligne
- Intro : 4-5 phrases = ~300 caractères
- Tendances : 2-3 × 2 phrases = ~350 caractères  
- Faits marquants : 5 × 2 phrases = ~700 caractères
- Ce qu'on en pense : 3-4 phrases = ~300 caractères
- Hashtags : 1 ligne
- Langue : français intégral, termes techniques en anglais acceptés
- Aucun emoji sauf ⚡ sur la ligne Cyber Brief
- 1 saut de ligne entre chaque bloc
- Les titres de section (Les tendances, Les faits marquants, Ce qu'on en pense) sont visibles dans le post — format sobre, en gras

TOTAL CIBLE : 2400–2600 caractères

MOTS INTERDITS :
"crucial" / "important" / "partager" / "liker" /
"Dans un monde où" / "Il est essentiel de" /
"force est de constater" / "paysage des menaces" /
"acteurs malveillants" / "la sécurité n'est pas un luxe" /
tout consensus mou / toute conclusion qui rassure sans raison\
"""

DEFAULTS = {
    "daily_synthesis": DEFAULT_DAILY,
    "weekly_synthesis": DEFAULT_WEEKLY,
    "weekly_cyberbrief": DEFAULT_CYBERBRIEF,
}


@admin_prompts_bp.route("/", methods=["GET"])
@login_required
@admin_required
def index():
    """Page de gestion des prompts LLM."""
    from models.prompt_config import PromptConfig

    prompts = {}
    for key in PromptConfig.KNOWN_KEYS:
        obj = PromptConfig.get(key)
        prompts[key] = {
            "key": key,
            "label": PromptConfig.LABELS[key],
            "description": PromptConfig.DESCRIPTIONS[key],
            "content": obj.content if obj else "",
            "default": DEFAULTS.get(key, ""),
            "updated_at": obj.updated_at if obj else None,
            "updated_by": obj.updated_by if obj else None,
            "is_custom": obj is not None,
        }

    return render_template("admin/prompts.html", prompts=prompts)


@admin_prompts_bp.route("/save", methods=["POST"])
@login_required
@admin_required
def save():
    """Enregistre un prompt personnalisé."""
    from models.prompt_config import PromptConfig

    key = request.form.get("prompt_key", "").strip()
    content = request.form.get("content", "").strip()

    if key not in PromptConfig.KNOWN_KEYS:
        flash("Clé de prompt invalide.", "danger")
        return redirect(url_for("admin_prompts.index"))

    if not content:
        flash("Le contenu du prompt ne peut pas être vide.", "warning")
        return redirect(url_for("admin_prompts.index"))

    PromptConfig.set(key, content, updated_by=current_user.email)
    label = PromptConfig.LABELS.get(key, key)
    flash(f"Prompt « {label} » enregistré avec succès.", "success")
    logger.info(f"Prompt '{key}' mis à jour par {current_user.email}")
    return redirect(url_for("admin_prompts.index"))


@admin_prompts_bp.route("/reset", methods=["POST"])
@login_required
@admin_required
def reset():
    """Remet un prompt à sa valeur par défaut (supprime la config en base)."""
    from models.prompt_config import PromptConfig

    key = request.form.get("prompt_key", "").strip()

    if key not in PromptConfig.KNOWN_KEYS:
        flash("Clé de prompt invalide.", "danger")
        return redirect(url_for("admin_prompts.index"))

    obj = PromptConfig.get(key)
    if obj:
        db.session.delete(obj)
        db.session.commit()
        label = PromptConfig.LABELS.get(key, key)
        flash(f"Prompt « {label} » remis à la valeur par défaut.", "success")
        logger.info(f"Prompt '{key}' réinitialisé par {current_user.email}")
    else:
        flash("Ce prompt utilisait déjà la valeur par défaut.", "info")

    return redirect(url_for("admin_prompts.index"))


@admin_prompts_bp.route("/default/<key>", methods=["GET"])
@login_required
@admin_required
def get_default(key: str):
    """API JSON : retourne le prompt par défaut pour une clé donnée."""
    from models.prompt_config import PromptConfig

    if key not in PromptConfig.KNOWN_KEYS:
        return jsonify({"error": "Clé inconnue"}), 404

    return jsonify({"key": key, "default": DEFAULTS.get(key, "")})
