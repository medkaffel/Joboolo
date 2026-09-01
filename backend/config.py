"""P0-001 — Configuration centralisée et validation des secrets.

Cette source unique de vérité lit les variables d'environnement critiques pour
P0-001 (APP_ENV, SECRET_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET).

Règles appliquées (décisions validées pour P0-001) :
- APP_ENV est OBLIGATOIRE dans tous les environnements (development|test|production).
  S'il est absent ou invalide, on fail-fast au démarrage, jamais silencieusement.
- SECRET_KEY est OBLIGATOIRE dans tous les environnements. Aucun fallback codé en dur.
- STRIPE_SECRET_KEY et STRIPE_WEBHOOK_SECRET sont obligatoires en production,
  optionnels en development/test.
- Le fail-fast principal a lieu au démarrage FastAPI (startup), PAS à l'import.
- Aucun secret ne doit apparaître dans les logs ni les messages d'erreur.

Le chargement reste LAZY : importer ce module ne doit jamais crasher. La validation
strict n'est appelée explicitement qu'au démarrage via validate_startup_config().
"""

import os
from dataclasses import dataclass
from typing import Optional

APP_ENV_DEVELOPMENT = "development"
APP_ENV_TEST = "test"
APP_ENV_PRODUCTION = "production"

VALID_APP_ENVS = frozenset({APP_ENV_DEVELOPMENT, APP_ENV_TEST, APP_ENV_PRODUCTION})

# Secrets connus historiquement codés en dur : leur présence doit être refusée,
# car ils ne sont pas des configurations valides.
FORBIDDEN_SECRET_VALUES = frozenset({
    "your-secret-key-change-this-in-production",
    "sk_test_emergent",
})

# Nom des variables lues centralement. Ne jamais logger leur VALEUR, uniquement
# leur NOM dans les messages d'erreur.
ENV_APP_ENV = "APP_ENV"
ENV_SECRET_KEY = "SECRET_KEY"
ENV_STRIPE_SECRET_KEY = "STRIPE_SECRET_KEY"
ENV_STRIPE_WEBHOOK_SECRET = "STRIPE_WEBHOOK_SECRET"


class ConfigurationError(RuntimeError):
    """Erreur explicite de configuration P0-001, ne contenant aucun secret."""


@dataclass(frozen=True)
class Settings:
    APP_ENV: str
    SECRET_KEY: Optional[str]
    STRIPE_SECRET_KEY: Optional[str]
    STRIPE_WEBHOOK_SECRET: Optional[str]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == APP_ENV_PRODUCTION

    @property
    def is_test(self) -> bool:
        return self.APP_ENV == APP_ENV_TEST


_settings: Optional[Settings] = None


def _raw(name: str, default: Optional[str] = None) -> Optional[str]:
    """Retourne la valeur brute d'une variable (jamais de secret dur dans le repo)."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _validate_secret_value(name: str, value: Optional[str]) -> Optional[str]:
    """Refuse une valeur secrète connue comme invalide, sans la divulguer."""
    if value is not None and value in FORBIDDEN_SECRET_VALUES:
        raise ConfigurationError(
            f"{name} est défini à une valeur connue/non fiable. "
            "Fournissez une vraie configuration via l'API des secrets (jamais de secret dur)."
        )
    return value


def load_settings() -> Settings:
    """Lit et retourne (et mémorise) la configuration. Strict sur APP_ENV / valeurs connues.

    N'échoue PAS à l'import : les exigences de présence (SECRET_KEY partout,
    Stripe en production) sont appliquées par validate_startup_config() au démarrage.
    """
    global _settings

    env_value = _raw(ENV_APP_ENV)
    if env_value is None:
        raise ConfigurationError(
            "La variable d'environnement APP_ENV est obligatoire. "
            f"Valeurs autorisées : {', '.join(sorted(VALID_APP_ENVS))}."
        )
    normalized_env = str(env_value).strip().lower()
    if normalized_env not in VALID_APP_ENVS:
        raise ConfigurationError(
            f"La variable d'environnement APP_ENV a une valeur inconnue. "
            "Ne jamais supposer un environnement silencieusement. "
            f"Valeurs autorisées : {', '.join(sorted(VALID_APP_ENVS))}."
        )

    secret_key = _validate_secret_value(ENV_SECRET_KEY, _raw(ENV_SECRET_KEY))
    stripe_secret_key = _validate_secret_value(ENV_STRIPE_SECRET_KEY, _raw(ENV_STRIPE_SECRET_KEY))
    stripe_webhook_secret = _validate_secret_value(
        ENV_STRIPE_WEBHOOK_SECRET, _raw(ENV_STRIPE_WEBHOOK_SECRET)
    )

    _settings = Settings(
        APP_ENV=normalized_env,
        SECRET_KEY=secret_key,
        STRIPE_SECRET_KEY=stripe_secret_key,
        STRIPE_WEBHOOK_SECRET=stripe_webhook_secret,
    )
    return _settings


def get_settings() -> Settings:
    """Accesseur lazy : charge une seule fois puis met en cache."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    """Réinitialise le cache (utile pour les tests isolés)."""
    global _settings
    _settings = None


def ensure_seeding_allowed() -> None:
    """Garde anti-production pour toute opération de seed / création de démo.

    P0-002 : refus explicite de renseigner la base avec des comptes/offres/
    entreprises de démonstration lorsque l'environnement est 'production'.
    Appelée AVANT toute écriture DB. Ne divulgue aucun secret.
    """
    if get_settings().is_production:
        raise ConfigurationError(
            "Le seed de données de démonstration est interdit en environnement "
            "production. Aucune donnée de démonstration ne doit être créée en production."
        )


def validate_startup_config() -> Settings:
    """Fail-fast au démarrage. Appelé par server.py AVANT seed/scheduler.

    Applique :
    - APP_ENV obligatoire et valide (déjà garanti par load_settings) ;
    - SECRET_KEY obligatoire dans TOUS les environnements ;
    - Stripe obligatoire en production.
    """
    settings = get_settings()

    if not settings.SECRET_KEY:
        raise ConfigurationError(
            "SECRET_KEY est obligatoire dans tous les environnements. "
            "Fournissez-la via l'API des secrets."
        )

    if settings.is_production:
        if not settings.STRIPE_SECRET_KEY:
            raise ConfigurationError(
                "STRIPE_SECRET_KEY est obligatoire en environnement production. "
                "Le backend refuse de démarrer sans elle."
            )
        if not settings.STRIPE_WEBHOOK_SECRET:
            raise ConfigurationError(
                "STRIPE_WEBHOOK_SECRET est obligatoire en environnement production. "
                "Le backend refuse de démarrer sans elle."
            )

    return settings