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
        articles_text = self._format_articles_for_prompt(articles, max_articles=20)

        prompt = f"""Tu es un expert en veille informationnelle. Analyse les articles suivants collectés le {date_str} dans la catégorie "{category_name}" et génère une synthèse structurée.

ARTICLES DU JOUR :
{articles_text}

CONSIGNES :
- Synthèse de 200 à 300 mots maximum
- Style informatif et professionnel
- Extraire les 3 à 5 tendances clés observées
- Citer les sources (noms des sites/médias)
- Utiliser des bullet points pour la lisibilité
- Langue : français

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

        return self._call_llm(prompt, max_tokens=800)

    def generate_weekly_synthesis(
        self,
        articles: List[Dict],
        category_name: str,
        week_start: Optional[date] = None,
        week_end: Optional[date] = None
    ) -> Tuple[Dict[str, str], int]:
        """
        Génère une synthèse hebdomadaire avec draft LinkedIn.

        Returns:
            Tuple (dict avec content/key_facts/trends/draft_linkedin, tokens_utilisés)
        """
        if not articles:
            empty = {
                "content": "Aucun article collecté cette semaine pour cette catégorie.",
                "key_facts": "",
                "trends": "",
                "draft_linkedin": "",
            }
            return empty, 0

        if not week_start:
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
        if not week_end:
            week_end = week_start + timedelta(days=6)

        period = f"du {week_start.strftime('%d/%m')} au {week_end.strftime('%d/%m/%Y')}"
        articles_text = self._format_articles_for_prompt(articles, max_articles=40)

        prompt = f"""Tu es un expert en veille informationnelle et en création de contenu LinkedIn. Analyse les articles de la semaine {period} dans la catégorie "{category_name}" et génère une synthèse hebdomadaire complète.

ARTICLES DE LA SEMAINE :
{articles_text}

CONSIGNES GÉNÉRALES :
- Langue : français
- Style professionnel et engageant
- Citer les sources

Génère une réponse structurée avec les 4 sections suivantes, séparées par des marqueurs :

===SYNTHESE===
[Synthèse générale de la semaine en 400-500 mots. Couvrir les événements majeurs, les annonces importantes, les évolutions du secteur. Style informatif.]

===FAITS_MARQUANTS===
[Liste des 5-7 faits marquants de la semaine sous forme de bullet points avec source et date]
• [Fait 1] — Source : [nom]
• [Fait 2] — Source : [nom]
...

===TENDANCES===
[Liste des 3-5 tendances majeures observées cette semaine sous forme de bullet points]
• [Tendance 1 : explication]
• [Tendance 2 : explication]
...

===DRAFT_LINKEDIN===
[Draft de post LinkedIn prêt à publier, 150-200 mots]

🔍 [Accroche percutante sur une ligne]

[Corps du post en 3-4 paragraphes courts, style conversationnel, chiffres et faits concrets]

[Conclusion avec appel à l'action ou question ouverte]

#hashtag1 #hashtag2 #hashtag3 #hashtag4 #hashtag5
"""

        content, tokens = self._call_llm(prompt, max_tokens=2000)

        # Parser les sections
        result = self._parse_weekly_response(content)
        return result, tokens

    def _format_articles_for_prompt(self, articles: List[Dict], max_articles: int = 30) -> str:
        """Formate les articles pour l'inclusion dans un prompt."""
        # Limiter le nombre d'articles
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
                # Tronquer le contenu
                content = article["content"][:500]
                lines.append(f"   Résumé : {content}")
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
