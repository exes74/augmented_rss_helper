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
        self.max_tokens_daily = config.get("LLM_MAX_TOKENS_DAILY", 500000)
        self.max_tokens_weekly = config.get("LLM_MAX_TOKENS_WEEKLY", 1000000)

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
...

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

        # ─── Prompt 1 : Super-synthèse + Faits + Tendances ───
        prompt_synthese = f"""Tu es un expert en veille informationnelle. \
Tu disposes des synthèses quotidiennes de la semaine {period} pour la catégorie "{category_name}".
Ta mission : produire une super-synthèse hebdomadaire à partir de ces synthèses.

SYNTHÈSES QUOTIDIENNES DE LA SEMAINE ({len(daily_syntheses)} jours, {total_articles} articles au total) :
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
...
"""

        # ─── Prompt 2 : Cyber Brief LinkedIn (prompt utilisateur, verbatim) ───
        week_start_str = week_start.strftime("%d")
        week_end_str = week_end.strftime("%d %B %Y")
        prompt_linkedin = f"""Tu es un expert en cybersécurité, style analytique, légèrement impertinent.
Audience : professionnels cyber (RSSI, analystes, pentesters) avec quelques profils mixtes.

Tu reçois {len(daily_syntheses)} synthèses quotidiennes au format suivant :
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

[INTRO — formulée en 4 à 5 phrases digestes]
Ce que cette semaine dit du secteur, en une lecture transversale.
Pas un résumé des 7 jours. Une lecture.
1 donnée chiffrée si elle est disponible dans les synthèses.

Les tendances

[2-3 tendances, formulées en 1-2 phrases chacune]
Une tendance = un fil qui traverse plusieurs faits, pas la répétition d'un fait.
Formuler ce qui monte, ce qui bascule, ce qui se confirme.
Impertinence autorisée si le consensus du secteur mérite d'être challengé.

Les faits marquants

1. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

2. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

3. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

4. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

5. [Titre court du fait]
[1-2 phrases : le fait, son contexte immédiat, pourquoi il compte]

→ Critères de sélection des 5 faits :
- Impact réel ou potentiel sur les organisations
- Nouveauté (pas une énième variante d'une menace connue)
- Révélateur d'une tendance plus large
- Diversité : ne pas prendre 5 faits du même registre (ex : 5 vulnérabilités)
- Faits mentionnés dans plusieurs syntheses différentes

Ce qu'on en pense

[3-4 phrases]
Pas de conclusion rassurante. Pas de morale.
Une perspective constructive : ce qui avance, ce qui protège mieux,
ce qui mérite d'être suivi la semaine prochaine.
Ton sobre. 1 ou 2 idées fortes.

#Cybersécurité #[HashtagNiche1] #[HashtagNiche2] #RSSI

═══ CONTRAINTES ═══

FOND :
- Croiser les {len(daily_syntheses)} synthèses, pas les additionner
- Les tendances doivent être transversales (au moins 2 synthèses différentes)
- 0 fait inventé ou extrapolé au-delà des sources

FORME :
- 3000 Caractères maximum  AU TOTAL(afficher le total) - recompter les caractères en fin d'exercice et restructurer si supérieur à 3000 caractères
- Langue : français intégral, termes techniques en anglais acceptés
- Aucun emoji sauf ⚡ sur la ligne Cyber Brief
- 1 saut de ligne entre chaque bloc
- Les titres de section (Les tendances, Les faits marquants, Ce qu'on en pense) sont visibles dans le post — format sobre, en gras

MOTS INTERDITS :
"crucial" / "important" / "partager" / "liker" /
"Dans un monde où" / "Il est essentiel de" /
"force est de constater" / "paysage des menaces" /
"acteurs malveillants" / "la sécurité n'est pas un luxe" /
tout consensus mou / toute conclusion qui rassure sans raison
"""

        # Appel LLM en deux étapes
        logger.info(f"Super-synthèse hebdo — étape 1 : synthèse + faits + tendances")
        content_raw, tokens_1 = self._call_llm(prompt_synthese, max_tokens=2000)
        if category_name == 'CyberSecurity':
            logger.info(f"Super-synthèse hebdo — étape 2 : draft LinkedIn Cyber Brief")
            linkedin_raw, tokens_2 = self._call_llm(prompt_linkedin, max_tokens=10000)
        else:
             linkedin_raw, tokens_2 = '',0
        # Parser les sections de la synthèse
        result = self._parse_weekly_response(content_raw)
        result["draft_linkedin"] = linkedin_raw.strip()

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
        "LLM_MAX_TOKENS_DAILY": config.get("LLM_MAX_TOKENS_DAILY", 500000),
        "LLM_MAX_TOKENS_WEEKLY": config.get("LLM_MAX_TOKENS_WEEKLY", 1000000),
    })
