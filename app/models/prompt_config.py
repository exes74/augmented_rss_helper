"""
Modèle de configuration des prompts LLM.
Permet de personnaliser les prompts de génération de synthèses depuis l'interface admin.
"""
from datetime import datetime, timezone
from main import db


class PromptConfig(db.Model):
    """
    Stocke les prompts LLM configurables par l'administrateur.

    Chaque entrée correspond à un prompt identifié par une clé unique (prompt_key).
    Si aucune entrée n'existe pour une clé, le code utilise le prompt par défaut
    codé en dur dans ai_synthesizer.py.

    Clés disponibles :
      - daily_synthesis      : prompt de génération des synthèses quotidiennes
      - weekly_synthesis     : prompt de super-synthèse hebdomadaire (partie 1)
      - weekly_cyberbrief    : prompt du Cyber Brief LinkedIn (partie 2 hebdo)
    """

    __tablename__ = "prompt_configs"

    # Clés de prompts reconnues
    KEY_DAILY = "daily_synthesis"
    KEY_WEEKLY = "weekly_synthesis"
    KEY_CYBERBRIEF = "weekly_cyberbrief"

    KNOWN_KEYS = [KEY_DAILY, KEY_WEEKLY, KEY_CYBERBRIEF]

    LABELS = {
        KEY_DAILY: "Synthèse quotidienne",
        KEY_WEEKLY: "Super-synthèse hebdomadaire",
        KEY_CYBERBRIEF: "Cyber Brief LinkedIn (hebdomadaire)",
    }

    DESCRIPTIONS = {
        KEY_DAILY: (
            "Prompt envoyé au LLM pour générer la synthèse quotidienne d'une catégorie. "
            "Variables disponibles : {date_str}, {category_name}, {articles_count}, {articles_text}."
        ),
        KEY_WEEKLY: (
            "Prompt envoyé au LLM pour générer la super-synthèse hebdomadaire "
            "(synthèse principale + faits marquants + tendances). "
            "Variables disponibles : {period}, {category_name}, {nb_days}, "
            "{total_articles}, {syntheses_text}."
        ),
        KEY_CYBERBRIEF: (
            "Prompt envoyé au LLM pour générer le Cyber Brief LinkedIn hebdomadaire. "
            "Utilisé uniquement pour les catégories dont le nom contient 'Cyber'. "
            "Variables disponibles : {nb_days}, {syntheses_text}, "
            "{week_start_str}, {week_end_str}."
        ),
    }

    id = db.Column(db.Integer, primary_key=True)
    prompt_key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    content = db.Column(db.Text, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by = db.Column(db.String(255), nullable=True)  # email de l'admin

    def __repr__(self) -> str:
        return f"<PromptConfig key={self.prompt_key}>"

    @classmethod
    def get(cls, key: str) -> "PromptConfig | None":
        """Retourne la config pour une clé, ou None si non configurée."""
        return cls.query.filter_by(prompt_key=key).first()

    @classmethod
    def get_content(cls, key: str, default: str = "") -> str:
        """Retourne le contenu du prompt, ou default si non configuré."""
        obj = cls.get(key)
        return obj.content if obj else default

    @classmethod
    def set(cls, key: str, content: str, updated_by: str = "") -> "PromptConfig":
        """Crée ou met à jour un prompt."""
        obj = cls.get(key)
        if obj is None:
            obj = cls(prompt_key=key, content=content, updated_by=updated_by)
            db.session.add(obj)
        else:
            obj.content = content
            obj.updated_by = updated_by
            obj.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return obj
