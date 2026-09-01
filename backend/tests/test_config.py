"""Tests P0-001 — configuration centralisée et fail-fast des secrets.

Tests unitaires sur config.py : ils ne nécessitent aucun serveur démarré et ne
touchent jamais à la production. Ils manipulent uniquement l'environnement Python
du process de test et réinitialisent le cache de config entre chaque cas.
"""

import os
import sys
from pathlib import Path

import pytest

# Permet d'importer le module config du backend depuis n'importe quel cwd.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config  # noqa: E402

# Seules ces variables sont manipulées par les tests : elles sont sauvegardées
# et restaurées ciblées pour ne jamais altérer l'environnement du process pytest
# (ex. PYTEST_CURRENT_TEST / PYTEST_XDIST_WORKER gérés par pytest lui-même).
_CONFIG_ENV_VARS = ("APP_ENV", "SECRET_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")


@pytest.fixture(autouse=True)
def _reset_config_state(monkeypatch):
    """Réinitialise le cache de config et restaure uniquement les variables P0 touchées."""
    saved = {key: os.environ.get(key) for key in _CONFIG_ENV_VARS}
    config.reset_settings()
    yield
    config.reset_settings()
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _set_env(**kwargs):
    for key, value in kwargs.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class TestAppEnv:
    def test_absent_app_env_raises(self, monkeypatch):
        _set_env(APP_ENV=None)
        with pytest.raises(config.ConfigurationError):
            config.load_settings()

    def test_invalid_app_env_raises(self, monkeypatch):
        _set_env(APP_ENV="staging-typo")
        with pytest.raises(config.ConfigurationError):
            config.load_settings()

    def test_valid_development(self, monkeypatch):
        _set_env(APP_ENV="development", SECRET_KEY="dev-secret-not-a-real-key")
        settings = config.load_settings()
        assert settings.APP_ENV == "development"
        assert settings.is_production is False
        assert settings.is_test is False

    def test_valid_test(self, monkeypatch):
        _set_env(APP_ENV="test", SECRET_KEY="test-secret-fake")
        settings = config.load_settings()
        assert settings.APP_ENV == "test"
        assert settings.is_test is True

    def test_valid_production(self, monkeypatch):
        _set_env(APP_ENV="production", SECRET_KEY="a-very-long-prod-secret-32chars!", STRIPE_SECRET_KEY="pk_test_x", STRIPE_WEBHOOK_SECRET="whsec_x")
        settings = config.load_settings()
        assert settings.APP_ENV == "production"
        assert settings.is_production is True

    def test_app_env_case_insensitive(self, monkeypatch):
        _set_env(APP_ENV="Production", SECRET_KEY="x" * 32, STRIPE_SECRET_KEY="pk_test_x", STRIPE_WEBHOOK_SECRET="whsec_x")
        settings = config.load_settings()
        assert settings.APP_ENV == "production"


class TestForbiddenSecrets:
    @pytest.mark.parametrize("key", [
        "SECRET_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
    ])
    def test_forbidden_known_values_rejected(self, monkeypatch, key):
        _set_env(APP_ENV="development", SECRET_KEY="good-dev-key")
        forbidden = "your-secret-key-change-this-in-production" if key == "SECRET_KEY" else "sk_test_emergent"
        _set_env(**{key: forbidden})
        with pytest.raises(config.ConfigurationError):
            config.load_settings()

    def test_real_empty_stripe_allowed_in_development(self, monkeypatch):
        _set_env(APP_ENV="development", SECRET_KEY="dev-key")
        settings = config.load_settings()
        assert settings.STRIPE_SECRET_KEY is None
        assert settings.STRIPE_WEBHOOK_SECRET is None


class TestValidateStartupConfig:
    def test_missing_secret_key_fails_all_envs(self, monkeypatch):
        _set_env(APP_ENV="test", SECRET_KEY=None)
        with pytest.raises(config.ConfigurationError):
            config.validate_startup_config()

    def test_secret_key_present_dev_ok(self, monkeypatch):
        _set_env(APP_ENV="development", SECRET_KEY="dev-key-ok")
        settings = config.validate_startup_config()
        assert settings.SECRET_KEY == "dev-key-ok"

    def test_secret_key_present_without_stripe_dev_ok(self, monkeypatch):
        # En development/test, Stripe n'est pas obligatoire au démarrage.
        _set_env(APP_ENV="test", SECRET_KEY="test-key-ok")
        config.validate_startup_config()  # ne doit pas lever

    def test_production_requires_stripe_secret(self, monkeypatch):
        _set_env(APP_ENV="production", SECRET_KEY="x" * 32)
        with pytest.raises(config.ConfigurationError):
            config.validate_startup_config()

    def test_production_requires_webhook_secret(self, monkeypatch):
        _set_env(APP_ENV="production", SECRET_KEY="x" * 32, STRIPE_SECRET_KEY="sk_live_a")
        with pytest.raises(config.ConfigurationError):
            config.validate_startup_config()

    def test_production_fully_configured_ok(self, monkeypatch):
        _set_env(
            APP_ENV="production",
            SECRET_KEY="x" * 32,
            STRIPE_SECRET_KEY="sk_live_full",
            STRIPE_WEBHOOK_SECRET="whsec_live",
        )
        settings = config.validate_startup_config()
        assert settings.STRIPE_WEBHOOK_SECRET == "whsec_live"


class TestNoSecretsInErrors:
    def test_error_message_never_contains_secret_value(self, monkeypatch):
        secret_value = "sup3rs3cret-value-never-in-logs"
        _set_env(APP_ENV="test", SECRET_KEY=secret_value)
        config.validate_startup_config()
        try:
            raise config.ConfigurationError("appel de test")
        except config.ConfigurationError as exc:
            assert secret_value not in str(exc)

    def test_forbidden_error_is_explicit_without_value(self, monkeypatch):
        _set_env(APP_ENV="development", SECRET_KEY="sk_test_emergent")
        with pytest.raises(config.ConfigurationError) as exc_info:
            config.load_settings()
        msg = str(exc_info.value)
        assert "sk_test_emergent" not in msg  # la valeur n'est pas divulguée
        assert "SECRET_KEY" in msg  # mais le nom de la variable est explicite