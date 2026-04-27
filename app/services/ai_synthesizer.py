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
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5")
        # Pour les modèles de raisonnement (gpt-5-*, o1, o3), max_completion_tokens
        # inclut les tokens de raisonnement internes. Il faut une valeur élevée.
        # Défaut : 16000 (suffisant pour la synthèse + raisonnement gpt-5-nano)
        self.max_output_tokens = int(config.get("LLM_MAX_OUTPUT_TOKENS", 16000))

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

        # Prompt par défaut (codé en dur)
        default_prompt = f"""Analyse les {articles_count} articles suivants, collectés le {date_str} dans la catégorie "{category_name}", 
et génère une synthèse structurée selon le format ci-dessous.

---
ARTICLES ({articles_count} articles) :

{articles_text}
---

CONSIGNES DE RÉDACTION :
- Longueur totale : 500 à 700 mots (hors titres et bullet points)
- Style : informatif, professionnel, journalistique
- Chaque bullet point cite entre parenthèses le(s) média(s) source(s) : (Le Monde, Reuters…)
- Les points clés doivent refléter les informations mentionnées par PLUSIEURS articles (convergence)
- La section France ne concerne que les faits explicitement situés en France
- Les tendances sont des lectures transversales, pas des répétitions des points clés

FORMAT DE SORTIE (à respecter strictement) :

## Synthèse du {date_str} — {category_name}

**Résumé :** [4 à 5 phrases synthétisant les grandes lignes de l'actualité du jour dans cette catégorie]

---

**Points clés :** *(5 à 10 points, ordre décroissant d'importance)*

• [Point 1] *(Source)*
• [Point 2] *(Source)*
• [Point 3] *(Source)*
...

---

**Et en France ?** *(3 à 5 points — uniquement si des articles couvrent l'actualité française)*

• [Point 1 France] *(Source)*
• [Point 2 France] *(Source)*
...
> *(Si aucun article ne traite spécifiquement de la France, indiquer : "Aucune actualité française identifiée dans les sources du jour.")*

---

**Tendances observées :** *(3 à 5 tendances de fond, issues du croisement des articles)*

• **[Titre court de la tendance]** — [Explication en 1-2 phrases]
• **[Titre court de la tendance]** — [Explication en 1-2 phrases]
...

"""
        system_prompt = f"""Tu es un expert en veille informationnelle et en analyse de contenu médiatique. 
Tu produis des synthèses journalistiques rigoureuses, factuelles et structurées à partir de flux RSS.

Règles absolues :
- Tu rédiges UNIQUEMENT en français
- Tu traites la TOTALITÉ des articles fournis sans en ignorer aucun
- Tu ne génères JAMAIS de contenu inventé : chaque affirmation doit être traceable à un article source
- Tu utilises le gras UNIQUEMENT via la syntaxe Markdown "**texte**", jamais autrement
- Tu respectes scrupuleusement le format de sortie demandé, sans y ajouter ni retirer de section
        """

        # Utiliser le prompt personnalisé de la base si disponible
        try:
            from models.prompt_config import PromptConfig
            custom = PromptConfig.get_content(PromptConfig.KEY_DAILY)
            if custom:
                prompt = custom.format(
                    date_str=date_str,
                    category_name=category_name,
                    articles_count=len(articles),
                    articles_text=articles_text,
                )
                logger.debug("Prompt quotidien personnalisé utilisé")
            else:
                prompt = default_prompt
                sys_prompt = system_prompt
        except Exception as e:
            logger.warning(f"Impossible de charger le prompt personnalisé : {e}")
            prompt = default_prompt

        return self._call_llm(prompt, max_tokens=4000)

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
        default_prompt_synthese = f"""Tu disposes des synthèses quotidiennes de la semaine {period} pour la catégorie "{category_name}" 
({nb_days} jours couverts, {total_articles} articles traités au total).

Ta mission : produire une super-synthèse hebdomadaire analytique — pas une concaténation des journées.

---
SYNTHÈSES QUOTIDIENNES :

{syntheses_text}
---

CONSIGNES :
- Style : professionnel, analytique, orienté décideur
- Identifier les fils conducteurs qui traversent plusieurs journées
- Hiérarchiser : tous les faits ne se valent pas
- Les faits marquants et les tendances doivent être complémentaires, pas redondants :
    • Les faits marquants = ce qui s'est passé (factuel, daté, sourcé)
    • Les tendances = ce que ça révèle (analytique, transversal, prospectif)
- Chaque fait marquant doit mentionner la date et la/les source(s)
- Chaque tendance doit être titrée et expliquée en 2-3 phrases

FORMAT DE SORTIE (à respecter strictement) :

---

## Synthèse hebdomadaire — {category_name} | {period}

**Vue d'ensemble :**
[3 à 4 phrases maximum. Quelle a été la tonalité dominante de la semaine ? 
Quels grands thèmes ont structuré l'actualité ? Quel est le fait saillant absolu ?]

---

**Analyse de la semaine :** *(400 à 500 mots)*
[Lecture transversale et structurée de la semaine. 
Identifier les fils conducteurs entre les journées, les ruptures, les accélérations, 
les contradictions éventuelles. Aller au-delà des faits : proposer une interprétation 
du contexte et des dynamiques à l'œuvre. Organiser en sous-thèmes si pertinent.]

---

**Faits marquants :** *(5 à 7 faits, ordre chronologique ou décroissant d'importance)*

• **[Titre court du fait]** — [Description concise] *(Date — Source)*
• **[Titre court du fait]** — [Description concise] *(Date — Source)*
...

---

**Ce que ça révèle — Tendances de fond :** *(3 à 5 tendances)*

• **[Titre de la tendance]** — [Explication en 2-3 phrases. En quoi cette tendance 
  dépasse-t-elle l'actualité immédiate ? Quelle dynamique structurelle illustre-t-elle ?]
• **[Titre de la tendance]** — [...]
...

---

**À surveiller la semaine prochaine :**
• [Signal faible ou sujet émergent identifié dans les sources]
• [Question ouverte ou développement attendu]
*(2 à 3 points maximum)*
"""
        # Utiliser le prompt personnalisé de la base si disponible
        try:
            from models.prompt_config import PromptConfig
            custom_weekly = PromptConfig.get_content(PromptConfig.KEY_WEEKLY)
            if custom_weekly:
                prompt_synthese = custom_weekly.format(
                    period=period,
                    category_name=category_name,
                    nb_days=len(daily_syntheses),
                    total_articles=total_articles,
                    syntheses_text=syntheses_text,
                )
                logger.debug("Prompt hebdomadaire personnalisé utilisé")
            else:
                prompt_synthese = default_prompt_synthese
        except Exception as e:
            logger.warning(f"Impossible de charger le prompt hebdomadaire personnalisé : {e}")
            prompt_synthese = default_prompt_synthese

        # ─── Prompt 2 : Cyber Brief LinkedIn (prompt utilisateur, verbatim) ───
        week_start_str = week_start.strftime("%d")
        week_end_str = week_end.strftime("%d %B %Y")
        default_prompt_linkedin = f"""Tu es un expert en cybersécurité avec 15 ans d'expérience opérationnelle.
Tu écris pour des professionnels qui n'ont pas besoin qu'on leur explique ce qu'est un CVE.

Ton style :
- Analytique, direct, légèrement impertinent
- Tu challenges les consensus mous du secteur quand ils le méritent
- Tu ne rassures pas pour rassurer
- Tu ne vulgarises pas : tu contextualises
- Zéro posture, zéro langue de bois

Règles de forme absolues :
- Français intégral, termes techniques anglais acceptés et non traduits
- Aucun emoji sauf ⚡ sur la ligne "Cyber Brief"
- Gras UNIQUEMENT via "**texte**"
- Mots et formules interdits (liste non exhaustive) :
  "crucial" / "important" / "partager" / "liker" / "Dans un monde où" /
  "Il est essentiel de" / "force est de constater" / "paysage des menaces" /
  "acteurs malveillants" / "la sécurité n'est pas un luxe" /
  tout consensus mou / toute conclusion rassurante sans fondement factuel
- 0 fait inventé, 0 extrapolation au-delà des sources fournies
- Respecter scrupuleusement les budgets de caractères par section

Tu reçois {nb_days} synthèses quotidiennes en cybersécurité couvrant la semaine 
du {week_start_str} au {week_end_str}.

---
SYNTHÈSES DE LA SEMAINE :

{syntheses_text}
---

MISSION : Produire un Cyber Brief hebdomadaire LinkedIn.
Croiser les synthèses, pas les additionner.
Cible : RSSI, analystes, pentesters — profils mixtes en minorité.

━━━ FORMAT DE SORTIE (strict) ━━━

[TITRE]
1 ligne. Sobre, factuel, légèrement impertinent.
Résume la semaine sans l'épuiser.
Pas de question. Pas d'exclamation. Pas de jeu de mots forcé.
Budget : ~60 caractères

⚡ Cyber Brief — Semaine du {week_start_str} au {week_end_str} : [TITRE]

**Contexte**
Ce que cette semaine révèle du secteur — pas un résumé des faits, une lecture.
1 donnée chiffrée si disponible dans les synthèses.
Budget : ~300 caractères

**Tendances**

• **[Titre tendance]** — [Ce qui monte, bascule ou se confirme.
  Impertinence autorisée si le consensus mérite d'être challengé.]
• **[Titre tendance]** — [...]
• **[Titre tendance]** — [...] *(optionnel)*

Règle : 1 tendance = 1 fil qui traverse ≥2 synthèses différentes, jamais la répétition d'un fait.
Budget : ~350 caractères

**Faits marquants**

1. **[Titre court]**
[Le fait + son contexte immédiat + pourquoi il compte. Sec et précis.]

2. **[Titre court]**
[...]

3. **[Titre court]**
[...]

4. **[Titre court]**
[...]

Critères de sélection :
→ Impact réel ou potentiel sur les organisations
→ Révélateur d'une dynamique plus large
→ Diversité des registres (pas 4 CVEs, pas 4 incidents du même type)
→ Présent dans plusieurs synthèses si possible
Budget : ~700 caractères

**À suivre**
Pas de morale. Pas de conclusion rassurante.
Ce qui avance, ce qui mérite attention la semaine prochaine.
1 ou 2 idées fortes, ton sobre.
Budget : ~300 caractères

#Cybersécurité #[HashtagNiche1] #[HashtagNiche2] #RSSI

━━━ BUDGETS & CIBLES ━━━

Section            | Cible
-------------------|------------------
Titre              | ~60 caractères
Intro Cyber Brief  | 1 ligne
Contexte           | ~300 caractères
Tendances          | ~350 caractères
Faits marquants    | ~700 caractères
À suivre           | ~300 caractères
Hashtags           | 1 ligne
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL CIBLE        | 2400–2600 caractères

1 saut de ligne entre chaque bloc.
Les titres de section sont visibles dans le post.
"""

        # Utiliser le prompt Cyber Brief personnalisé si disponible
        try:
            from models.prompt_config import PromptConfig
            custom_cyber = PromptConfig.get_content(PromptConfig.KEY_CYBERBRIEF)
            if custom_cyber:
                prompt_linkedin = custom_cyber.format(
                    nb_days=len(daily_syntheses),
                    syntheses_text=syntheses_text,
                    week_start_str=week_start_str,
                    week_end_str=week_end_str,
                )
                logger.debug("Prompt Cyber Brief personnalisé utilisé")
            else:
                prompt_linkedin = default_prompt_linkedin
        except Exception as e:
            logger.warning(f"Impossible de charger le prompt Cyber Brief personnalisé : {e}")
            prompt_linkedin = default_prompt_linkedin

        # Appel LLM en deux étapes
        logger.info(f"Super-synthèse hebdo — étape 1 : synthèse + faits + tendances")
        content_raw, tokens_1 = self._call_llm(prompt_synthese, max_tokens=5000)
        if 'Cyber' in category_name:
            logger.info(f"Super-synthèse hebdo — étape 2 : draft LinkedIn Cyber Brief")
            linkedin_raw, tokens_2 = self._call_llm(prompt_linkedin, max_tokens=2000)
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
        # Tronquer le prompt si nécessaire pour éviter les erreurs TPM 429
        prompt = self._truncate_prompt_to_limit(prompt)

        if self.provider == "openai":
            return self._call_openai(prompt, max_tokens)
        elif self.provider == "ollama":
            return self._call_ollama(prompt, max_tokens)
        elif self.provider == "claude":
            return self._call_claude(prompt, max_tokens)
        else:
            logger.error(f"Provider LLM inconnu : {self.provider}")
            return "Erreur : provider LLM non configuré.", 0

    def _call_claude(self, prompt: str, max_tokens: int = 1000) -> Tuple[str, int]:
        """Appelle l'API Anthropic Claude."""
        if not self.anthropic_api_key:
            logger.error("Clé API Anthropic manquante (ANTHROPIC_API_KEY non définie dans .env)")
            return "Erreur : clé API Anthropic non configurée.", 0

        try:
            import anthropic
            logger.debug(f"Versions : anthropic={anthropic.__version__}")

            client = anthropic.Anthropic(api_key=self.anthropic_api_key)

            response = client.messages.create(
                model=self.anthropic_model,  # ex: "claude-opus-4-5"
                max_tokens=max_tokens,
                system="Tu es un assistant expert en veille informationnelle et création de contenu professionnel. Tu réponds toujours en français.",
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
            )

            content = response.content[0].text
            tokens_used = response.usage.input_tokens + response.usage.output_tokens

            logger.info(
                f"Claude : {tokens_used} tokens utilisés "
                f"(input={response.usage.input_tokens}, output={response.usage.output_tokens}, "
                f"modèle={self.anthropic_model})"
            )
            return content, tokens_used

        except Exception as e:
            logger.error(f"Erreur API Anthropic : {e}", exc_info=True)
            return f"Erreur lors de la génération de la synthèse : {str(e)}", 0


    # Limite de tokens en entrée (input) par appel pour éviter les erreurs TPM 429.
    # gpt-5-nano : 200 000 TPM. On vise ~150 000 tokens max par requête pour garder
    # de la marge pour les autres requêtes simultanées.
    # Approximation : 1 token ≈ 4 caractères (français/anglais mélangé).
    _MAX_PROMPT_CHARS = int(os.environ.get("LLM_MAX_PROMPT_CHARS", 400_000))  # ~100k tokens

    def _truncate_prompt_to_limit(self, prompt: str) -> str:
        """
        Tronque le prompt si sa taille dépasse _MAX_PROMPT_CHARS.
        Essaie de couper proprement après un article complet (ligne vide)
        plutôt qu'en plein milieu d'un texte.
        """
        limit = self._MAX_PROMPT_CHARS
        if len(prompt) <= limit:
            return prompt

        logger.warning(
            f"Prompt trop long ({len(prompt)} caractères > {limit}) — troncature en cours"
        )

        # Couper au dernier saut de ligne double avant la limite
        truncated = prompt[:limit]
        last_break = truncated.rfind("\n\n")
        if last_break > limit // 2:  # Ne couper que si on garde au moins la moitié
            truncated = truncated[:last_break]

        # Ajouter une note pour indiquer au LLM que le contenu a été tronqué
        truncated += (
            "\n\n[NOTE : La liste d'articles a été tronquée pour respecter "
            "les limites de l'API. Génère la synthèse à partir des articles fournis.]"
        )
        logger.info(
            f"Prompt tronqué : {len(prompt)} → {len(truncated)} caractères "
            f"(~{len(truncated)//4} tokens estimés)"
        )
        return truncated

    # Modèles OpenAI qui nécessitent max_completion_tokens et temperature=1
    _OPENAI_NEW_API_MODELS = ("gpt-5", "o1", "o3", "o4")

    def _openai_uses_new_api(self) -> bool:
        """Retourne True si le modèle nécessite max_completion_tokens et temperature=1."""
        model = self.openai_model.lower()
        return any(model.startswith(prefix) for prefix in self._OPENAI_NEW_API_MODELS)

    def _call_openai(self, prompt: str, max_tokens: int = 1000) -> Tuple[str, int]:
        """Appelle l'API OpenAI.

        Gère automatiquement les différences de paramètres selon le modèle :
        - Anciens modèles (gpt-4.x, gpt-3.5) : max_tokens + temperature=0.7
        - Nouveaux modèles (gpt-5-*, o1, o3) : max_completion_tokens + temperature=1
        """
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

            # Adapter les paramètres selon le modèle
            new_api = self._openai_uses_new_api()
            call_kwargs = {
                "model": self.openai_model,
                "messages": [
                    {
                        "role": "system",
                        "content": f"""Tu es un expert en veille informationnelle et en analyse de contenu médiatique. 
                            Tu produis des synthèses journalistiques rigoureuses, factuelles et structurées à partir de flux RSS.

                            Règles absolues :
                            - Tu rédiges UNIQUEMENT en français
                            - Tu traites la TOTALITÉ des articles fournis sans en ignorer aucun
                            - Tu ne génères JAMAIS de contenu inventé : chaque affirmation doit être traceable à un article source
                            - Tu utilises le gras UNIQUEMENT via la syntaxe Markdown "**texte**", jamais autrement
                            - Tu respectes scrupuleusement le format de sortie demandé, sans y ajouter ni retirer de section
                            - Les tendances ne sont PAS une reformulation des faits marquants : elles constituent une lecture de fond, prospective si possible
                            """
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
            }
            if new_api:
                # gpt-5-* et modèles o-series : max_completion_tokens, temperature forcée à 1
                # Ces modèles de raisonnement consomment des tokens internes (thinking)
                # qui comptent dans max_completion_tokens — il faut une valeur élevée.
                # On prend le max entre max_tokens demandé et LLM_MAX_OUTPUT_TOKENS (défaut 16000)
                effective_max = max(max_tokens, self.max_output_tokens)
                call_kwargs["max_completion_tokens"] = effective_max
                # temperature=1 est la seule valeur supportée, on ne la passe pas
                # (valeur par défaut) pour éviter l'erreur 400
                logger.debug(f"Appel OpenAI new-API : max_completion_tokens={effective_max} (demandé={max_tokens}, max_output={self.max_output_tokens})")
            else:
                # Anciens modèles : max_tokens + temperature
                call_kwargs["max_tokens"] = max_tokens
                call_kwargs["temperature"] = 0.4
                logger.debug(f"Appel OpenAI legacy-API : max_tokens={max_tokens}, temperature=0.4,top_p=0.9, frequency_penalty=0.3,  presence_penalty=0.1,")

            response = client.chat.completions.create(**call_kwargs)

            choice = response.choices[0]
            content = choice.message.content
            finish_reason = choice.finish_reason
            tokens_used = response.usage.total_tokens if response.usage else 0

            logger.info(
                f"OpenAI : {tokens_used} tokens utilisés (modèle={self.openai_model}, "
                f"finish_reason={finish_reason})"
            )

            # Avec gpt-5-* et o-series, content peut être None si la réponse est tronquée
            # ou si le modèle n'a pas pu générer de réponse (finish_reason='length')
            if content is None:
                logger.error(
                    f"OpenAI a retourné content=None (finish_reason={finish_reason}). "
                    f"Augmenter max_completion_tokens ou réduire LLM_MAX_PROMPT_CHARS."
                )
                return (
                    f"[Erreur : la réponse du modèle est vide (finish_reason={finish_reason}). "
                    f"Essayez de régénérer ou de réduire le nombre d'articles.]",
                    tokens_used
                )

            if finish_reason == "length":
                logger.warning(
                    f"OpenAI : réponse tronquée (finish_reason=length, max_tokens={max_tokens}). "
                    f"Considérer d'augmenter max_completion_tokens."
                )

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
        # Pour les modèles de raisonnement (gpt-5-*, o1, o3) : limite de tokens de sortie
        # (inclut les tokens de raisonnement internes). Défaut : 16000.
        "LLM_MAX_OUTPUT_TOKENS": config.get("LLM_MAX_OUTPUT_TOKENS", 16000),
    })
