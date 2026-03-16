"""
Service de génération de synthèses par IA.
Supporte OpenAI (API) et Ollama (LLM local).
"""
import logging
import os
from datetime import datetime, timezone, timedelta, date
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


class AISynthesizer:
    """Génère des synthèses intelligentes à partir d'articles RSS."""

    def __init__(self, config: Dict[str, Any]):
        self.provider = config.get("LLM_PROVIDER", "openai")
        self.openai_api_key = config.get("OPENAI_API_KEY", "")
        self.openai_model = config.get("OPENAI_MODEL", "gpt-4o-mini")
        self.ollama_base_url = config.get("OLLAMA_BASE_URL", "http://ollama:11434")
        self.ollama_model = config.get("OLLAMA_MODEL", "llama3.1")
        self.max_tokens_daily = config.get("LLM_MAX_TOKENS_DAILY", 50000)
        self.max_tokens_weekly = config.get("LLM_MAX_TOKENS_WEEKLY", 100000)

    def generate_daily_synthesis(
        self,
        articles: List[Dict],
        category_name: str,
        target_date: Optional[date] = None
    ) -> Tuple[str, int]:
        """
        Génère une synthèse quotidienne pour une catégorie.

        Args:
            articles: Liste des articles du jour
            category_name: Nom de la catégorie
            target_date: Date cible (par défaut aujourd'hui)

        Returns:
            Tuple (synthèse_texte, tokens_utilisés)
        """
        if not articles:
            return "Aucun article collecté pour cette catégorie aujourd'hui.", 0

        date_str = (target_date or date.today()).strftime("%d/%m/%Y")
        # Tous les articles, sans limite de nombre ni troncature du contenu
        articles_text = self._format_articles_for_prompt(articles, max_articles=None, truncate_content=False)

        prompt = f"""Tu es un expert en veille informationnelle. Analyse les articles suivants collectés le {date_str} dans la catégorie "{category_name}" et génère une synthèse structurée.

ARTICLES DU JOUR ({len(articles)} articles) :
{articles_text}

CONSIGNES :
- Synthèse de 400 à 600 mots
- Style informatif et professionnel
- Extraire les 3 à 5 tendances clés observées
- Citer les sources (noms des sites/médias)
- Utiliser des bullet points pour la lisibilité
- Langue : français
- Prendre en compte TOUS les articles fournis

FORMAT ATTENDU :
## Synthèse du {date_str} — {category_name}

**Résumé :** [2-3 phrases de résumé général]

**Points clés :**
• [Point 1 avec source]
• [Point 2 avec source]
• [Point 3 avec source]

**Tendances observées :**
• [Tendance 1]
• [Tendance 2]
"""

        return self._call_llm(prompt, max_tokens=2000)

    def generate_weekly_synthesis(
        self,
        daily_syntheses: List[Dict],
        category_name: str,
        week_start: Optional[date] = None,
        week_end: Optional[date] = None,
        week_number: Optional[int] = None,
    ) -> Tuple[Dict[str, str], int]:
        """
        Génère une super-synthèse hebdomadaire à partir des synthèses quotidiennes.

        Args:
            daily_syntheses: Liste de dicts {date, content, articles_count}
                             représentant les synthèses quotidiennes de la semaine
            category_name: Nom de la catégorie
            week_start: Lundi de la semaine de référence
            week_end: Dimanche de la semaine de référence
            week_number: Numéro ISO de la semaine (pour le Cyber Brief)

        Returns:
            Tuple (dict avec content/key_facts/trends/draft_linkedin, tokens_utilisés)
        """
        if not daily_syntheses:
            empty = {
                "content": "Aucune synthèse quotidienne disponible pour cette semaine.",
                "key_facts": "",
                "trends": "",
                "draft_linkedin": "",
            }
            return empty, 0

        if not week_start:
            today = date.today()
            week_start = today - timedelta(days=today.weekday() + 7)
        if not week_end:
            week_end = week_start + timedelta(days=6)
        if not week_number:
            week_number = week_start.isocalendar()[1]

        period = f"du {week_start.strftime('%d/%m')} au {week_end.strftime('%d/%m/%Y')}"
        date_str = week_start.strftime("%d %B %Y")
        total_articles = sum(s.get("articles_count", 0) for s in daily_syntheses)

        # Formater les synthèses quotidiennes pour le prompt
        syntheses_text = ""
        for s in daily_syntheses:
            syntheses_text += f"\n--- Synthèse du {s['date']} ({s['articles_count']} articles) ---\n"
            syntheses_text += s["content"] + "\n"

        # ─── Prompt 1 : Super-synthèse (nouveau prompt utilisateur) ───
        week_start_str = week_start.strftime("%d")
        week_end_str = week_end.strftime("%d %B %Y")
        prompt_synthese = f"""Tu es un expert en cybersécurité, style analytique, légèrement impertinent.
Audience : professionnels cyber (RSSI, analystes, pentesters) avec quelques profils mixtes.

Tu reçois {len(daily_syntheses)} synthèses quotidiennes au format suivant :
- Résumé
- Points clés (bullets)
- Tendances observées

{syntheses_text}

═══ TÂCHE ═══

Produis une métasynthèse hebdomadaire structurée comme suit :

---

[TITRE]
Sobre, factuel, légèrement impertinent.
Résume la semaine sans l'épuiser.
Pas de question. Pas d'exclamation. Pas de jeu de mots forcé.
Exemples de ton acceptable :
→ "La semaine où l'IA est passée de l'autre côté"
→ "Quand la surface d'attaque grandit plus vite que les équipes"

⚡ Cyber Brief — Semaine du {week_start_str} au {week_end_str}

[INTRO — 3 lignes max]
Ce que cette semaine dit du secteur, en une lecture transversale.
Pas un résumé des 7 jours. Une lecture.
1 donnée chiffrée si elle est disponible dans les synthèses.

5 FAITS MARQUANTS DE LA SEMAINE

1. [Titre court du fait]
[2-3 lignes : le fait, son contexte immédiat, pourquoi il compte]

2. [Titre court du fait]
[2-3 lignes]

3. [Titre court du fait]
[2-3 lignes]

4. [Titre court du fait]
[2-3 lignes]

5. [Titre court du fait]
[2-3 lignes]

→ Critères de sélection des 5 faits :
- Impact réel ou potentiel sur les organisations
- Nouveauté (pas une énième variante d'une menace connue)
- Révélateur d'une tendance plus large
- Diversité : ne pas prendre 5 faits du même registre (ex : 5 vulnérabilités)

TENDANCES DE LA SEMAINE

[2-3 tendances, formulées en 2-3 lignes chacune]
Une tendance = un fil qui traverse plusieurs faits, pas la répétition d'un fait.
Formuler ce qui monte, ce qui bascule, ce qui se confirme.
Impertinence autorisée si le consensus du secteur mérite d'être challengé.

OUVERTURE

[3-4 lignes]
Pas de conclusion rassurante. Pas de morale.
Une perspective constructive : ce qui avance, ce qui protège mieux,
ce qui mérite d'être suivi la semaine prochaine.
Ton sobre. 1 seule idée forte.

#Cybersécurité #[HashtagNiche1] #[HashtagNiche2] #RSSI

[XXX mots]

═══ CONTRAINTES ═══

FOND :
- Croiser les {len(daily_syntheses)} synthèses, pas les additionner
- Les tendances doivent être transversales (au moins 2 synthèses différentes)
- 0 fait inventé ou extrapolé au-delà des sources

FORME :
- 450-550 mots strictement (afficher le total)
- Langue : français intégral, termes techniques en anglais acceptés
- Aucun emoji sauf ⚡ sur la ligne Cyber Brief
- 1 saut de ligne entre chaque bloc
- Les titres de section (5 FAITS, TENDANCES, OUVERTURE)
  sont visibles dans le post — format sobre, sans décoration

MOTS INTERDITS :
"crucial" / "important" / "partager" / "liker" /
"Dans un monde où" / "Il est essentiel de" /
"force est de constater" / "paysage des menaces" /
"acteurs malveillants" / "la sécurité n'est pas un luxe" /
tout consensus mou / toute conclusion qui rassure sans raison
"""

        # ─── Prompt 2 : Draft LinkedIn Cyber Brief ───
        prompt_linkedin = f"""Tu es Younes, expert en cybersécurité avec 13 ans d'expérience. \
Chaque vendredi tu publies ton "Cyber Brief" sur LinkedIn.
Voici les synthèses de ta veille de la semaine {period} (catégorie : {category_name}) :

{syntheses_text}

Génère le post LinkedIn "⚡ Cyber Brief #[NUMÉRO]" avec cette structure fixe :

═══ STRUCTURE IMPOSÉE ═══

Ligne 1 — ACCROCHE (jamais d'emoji, max 8 mots)
Format au choix :
→ "Ce que [X] ne te dit pas sur [Y]"
→ Question contre-intuitive sur l'actu dominante
→ Affirmation tranchée qui surprend

Saut de ligne
⚡ Cyber Brief #{week_number} — Semaine du {date_str}

Saut de ligne
🔴 1 MENACE
[1-2 lignes max : la menace la plus critique de la semaine]
[1 donnée chiffrée obligatoire]

Saut de ligne
🕳️ 1 FAILLE
[1-2 lignes max : la vulnérabilité à surveiller]
[Niveau de criticité + systèmes concernés]

Saut de ligne
🛡️ 1 BONNE PRATIQUE
[1-2 lignes max : action concrète et immédiate]
[Applicable sans budget / sans délai]

Saut de ligne
📊 1 CHIFFRE QUI DÉRANGE
[Stat marquante de la semaine]
[1 ligne de contexte qui rend ce chiffre percutant]

Saut de ligne
💡 L'INSIGHT DE LA SEMAINE
[Tendance transversale qui relie ces 4 éléments]
[Ton angle unique — ce que personne d'autre ne dira]
[Position tranchée, jamais de consensus mou]

Saut de ligne
[QUESTION CLIVANTE pour forcer les commentaires]
Exemples de format :
→ "Les RSSI que je croise pensent que [X]. Vous en êtes où ?"
→ "On fait quoi concrètement face à ça ?"
→ "C'est évitable ou on l'accepte comme une fatalité ?"

Saut de ligne
#Cybersécurité #[HashtagNiche1] #[HashtagNiche2] #RSSI

═══ CONTRAINTES ABSOLUES ═══

FOND :
- 1 insight original non présent dans les articles sources
- Zéro reformulation de ce qui existe déjà sur le fil
- Position assumée, jamais de "il faudrait peut-être"

FORME :
- 160-180 mots strictement
- Saut de ligne après CHAQUE phrase
- 1 emoji par section, uniquement ceux définis
- Mots INTERDITS : "crucial", "important", "partager", "liker", "abonnez-vous",
  "Dans un monde où", "Il est essentiel de", "force est de constater"
- Lien source → ne pas intégrer dans le post (sera posté en 1er commentaire)

ALGORITHME :
- Première ligne doit fonctionner SEULE avant le "voir plus"
- Proposer 2 variantes d'accroche (Variante A et Variante B) avant le post final
- Format identique chaque semaine (l'audience doit reconnaître la structure)

Réponds en français uniquement.
"""

        # Appel LLM en deux étapes
        logger.info(f"Super-synthèse hebdo — étape 1 : synthèse + faits + tendances")
        content_raw, tokens_1 = self._call_llm(prompt_synthese, max_tokens=2000)

        logger.info(f"Super-synthèse hebdo — étape 2 : draft LinkedIn Cyber Brief")
        linkedin_raw, tokens_2 = self._call_llm(prompt_linkedin, max_tokens=1000)

        # Le nouveau prompt produit un bloc unique structuré (pas de marqueurs ===)
        # On stocke le contenu complet dans 'content', key_facts et trends restent vides
        result = {
            "content": content_raw.strip(),
            "key_facts": "",
            "trends": "",
            "draft_linkedin": linkedin_raw.strip(),
        }

        return result, tokens_1 + tokens_2

    def _format_articles_for_prompt(
        self,
        articles: List[Dict],
        max_articles: Optional[int] = None,
        truncate_content: bool = True,
        content_max_chars: int = 500
    ) -> str:
        """Formate les articles pour l'inclusion dans un prompt.

        Args:
            articles: Liste des articles
            max_articles: Nombre maximum d'articles (None = tous)
            truncate_content: Si False, inclut le contenu complet
            content_max_chars: Nombre de caractères max par article si truncate_content=True
        """
        if max_articles is not None:
            articles = articles[:max_articles]

        lines = []
        for i, article in enumerate(articles, 1):
            pub_date = ""
            if article.get("published_at"):
                if isinstance(article["published_at"], datetime):
                    pub_date = article["published_at"].strftime("%d/%m/%Y")
                else:
                    pub_date = str(article["published_at"])[:10]

            lines.append(f"{i}. **{article.get('title', 'Sans titre')}**")
            if pub_date:
                lines.append(f"   Date : {pub_date}")
            if article.get("feed_name"):
                lines.append(f"   Source : {article['feed_name']}")
            if article.get("content"):
                content = article["content"]
                if truncate_content:
                    content = content[:content_max_chars]
                lines.append(f"   Contenu : {content}")
            lines.append(f"   URL : {article.get('url', '')}")
            lines.append("")

        return "\n".join(lines)

    def _parse_weekly_response(self, content: str) -> Dict[str, str]:
        """Parse la réponse structurée de la synthèse hebdomadaire."""
        result = {
            "content": "",
            "key_facts": "",
            "trends": "",
            "draft_linkedin": "",
        }

        sections = {
            "content": "===SYNTHESE===",
            "key_facts": "===FAITS_MARQUANTS===",
            "trends": "===TENDANCES===",
            "draft_linkedin": "===DRAFT_LINKEDIN===",
        }

        markers = list(sections.values())

        for key, marker in sections.items():
            if marker in content:
                start = content.index(marker) + len(marker)
                # Trouver la fin (prochain marqueur ou fin du texte)
                end = len(content)
                for other_marker in markers:
                    if other_marker != marker and other_marker in content:
                        pos = content.index(other_marker)
                        if pos > start and pos < end:
                            end = pos
                result[key] = content[start:end].strip()

        # Si le parsing échoue, mettre tout dans content
        if not any(result.values()):
            result["content"] = content

        return result

    def _call_llm(self, prompt: str, max_tokens: int = 1000) -> Tuple[str, int]:
        """
        Appelle le LLM configuré (OpenAI ou Ollama).

        Returns:
            Tuple (response_text, tokens_used)
        """
        if self.provider == "openai":
            return self._call_openai(prompt, max_tokens)
        elif self.provider == "ollama":
            return self._call_ollama(prompt, max_tokens)
        else:
            logger.error(f"Provider LLM inconnu : {self.provider}")
            return "Erreur : provider LLM non configuré.", 0

    def _call_openai(self, prompt: str, max_tokens: int = 1000) -> Tuple[str, int]:
        """Appelle l'API OpenAI."""
        # Vérification préalable de la clé API
        if not self.openai_api_key:
            logger.error("Clé API OpenAI manquante (OPENAI_API_KEY non définie dans .env)")
            return "Erreur : clé API OpenAI non configurée.", 0

        try:
            from openai import OpenAI
            import openai as _openai_module
            import httpx as _httpx_module
            logger.debug(
                f"Versions : openai={_openai_module.__version__}, "
                f"httpx={_httpx_module.__version__}"
            )

            client = OpenAI(api_key=self.openai_api_key)

            response = client.chat.completions.create(
                model=self.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un assistant expert en veille informationnelle et création de contenu professionnel. Tu réponds toujours en français."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=max_tokens,
                temperature=0.7,
            )

            content = response.choices[0].message.content
            tokens_used = response.usage.total_tokens if response.usage else 0

            logger.info(f"OpenAI : {tokens_used} tokens utilisés (modèle={self.openai_model})")
            return content, tokens_used

        except Exception as e:
            logger.error(f"Erreur API OpenAI : {e}", exc_info=True)
            return f"Erreur lors de la génération de la synthèse : {str(e)}", 0

    def _call_ollama(self, prompt: str, max_tokens: int = 1000) -> Tuple[str, int]:
        """Appelle l'API Ollama (LLM local)."""
        try:
            import requests

            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": 0.7,
                    }
                },
                timeout=120
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("response", "")
            # Ollama ne retourne pas directement les tokens, estimation
            tokens_used = len(prompt.split()) + len(content.split())

            logger.info(f"Ollama : réponse générée ({tokens_used} tokens estimés)")
            return content, tokens_used

        except Exception as e:
            logger.error(f"Erreur Ollama : {e}")
            return f"Erreur lors de la génération de la synthèse : {str(e)}", 0


def get_synthesizer(app=None) -> AISynthesizer:
    """Factory pour créer un synthesizer avec la configuration de l'app."""
    if app:
        config = app.config
    else:
        from flask import current_app
        config = current_app.config

    return AISynthesizer({
        "LLM_PROVIDER": config.get("LLM_PROVIDER", "openai"),
        "OPENAI_API_KEY": config.get("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": config.get("OPENAI_MODEL", "gpt-4o-mini"),
        "OLLAMA_BASE_URL": config.get("OLLAMA_BASE_URL", "http://ollama:11434"),
        "OLLAMA_MODEL": config.get("OLLAMA_MODEL", "llama3.1"),
        "LLM_MAX_TOKENS_DAILY": config.get("LLM_MAX_TOKENS_DAILY", 50000),
        "LLM_MAX_TOKENS_WEEKLY": config.get("LLM_MAX_TOKENS_WEEKLY", 100000),
    })
