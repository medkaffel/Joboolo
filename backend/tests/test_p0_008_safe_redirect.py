"""P0-008 : open redirect des alertes — validateur fail-safe + regression handler.

Le tracker `GET /api/alerts/track/{alert_id}` ne doit jamais rediriger vers une
origine externe arbitraire. Ce module teste :
- `safe_urls.safe_redirect` (validateur pur) sur la matrice open-redirect ;
- le round-trip des liens produits par `email_service._tracked()` ;
- le handler `track_alert_click` : le tracking (`last_viewed_at`,
  `click_count`, `last_alert_viewed_at`) est TOUJOURS effectué, et une
  destination invalide tombe sur `/`.

Nécessite aucun service externe ni Mongo : le handler est chargé via des stubs
et exercé directement.
"""
import asyncio
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import safe_urls  # noqa: E402
from email_service import _tracked  # noqa: E402

APP = "https://joboolo.fr"


def _refuses(target, app_url=APP):
    return safe_urls.safe_redirect(target, app_url) == "/"


def _keeps(target, app_url=APP):
    assert safe_urls.safe_redirect(target, app_url) == target


class TestAllowedRelative:
    @pytest.mark.parametrize("target,expected", [
        ("", "/"),
        (None, "/"),
        ("/", "/"),
        ("/jobs/123", "/jobs/123"),
        ("/jobs/123?utm=1&x=2", "/jobs/123?utm=1&x=2"),
        ("/jobs/123#frag", "/jobs/123#frag"),
        ("/profile", "/profile"),
        ("/jobs?x=%2F", "/jobs?x=%2F"),  # '%2F' en query interne : pas un netloc
    ])
    def test_safe_relative_kept(self, target, expected):
        assert safe_urls.safe_redirect(target, APP) == expected


class TestAllowedSameOriginAbsolute:
    @pytest.mark.parametrize("target", [
        "https://joboolo.fr",
        "https://joboolo.fr/",
        "https://joboolo.fr/jobs/123",
        "https://joboolo.fr:443/jobs/123",        # port par défaut explicite
        "https://joboolo.fr./jobs/123",           # point final normalisé (même hôte)
        "HTTPS://JOBoolo.FR/jobs/123",            # casse schéma/hôte normalisée
    ])
    def test_same_origin_kept(self, target):
        _keeps(target)


class TestRefused:
    @pytest.mark.parametrize("target", [
        "https://evil.example",
        "http://evil.example",
        "http://joboolo.fr/",                      # schéma différent de l'APP https
        "https://evil.example:443",
        "https://joboolo.fr:8080/jobs",            # port différent
        "//evil.example",
        "///evil.example",
        "////evil.example",
        "//JOBoolo.fr",                            # scheme-relative même hôte : refusé
        "/\\evil.example",                         # backslash après '/'
        "\\evil.example",
        "\\/evil.example",
        "https://good\\@evil.com",                 # backslash => hostname evil.com
        "https://evil@joboolo.fr",                 # userinfo
        "https://evil:pass@joboolo.fr",
        "https://joboolo.fr@evil.com",
        "https://sub.joboolo.fr",
        "https://eviljoboolo.fr",
        "https://joboolo.fr.evil.com",
        "https://.joboolo.fr",
        "https://joboolo.fr.evil.",
        "https://[::1]/jobs",                      # IPv6 d'une autre origine
        "https://[::1",                            # IPv6 mal formé (fail-safe)
        "javascript:alert(1)",
        "javascript://joboolo.fr/x",
        "data:text/html,<script>x</script>",
        "file:///etc/passwd",
        "ftp://joboolo.fr",
        "mailto:admin@joboolo.fr",
        " jobs/123",                               # blanc de tête
        " /jobs/123",
        " https://joboolo.fr/jobs/123",
        "jobs/123",                                # relatif sans '/' initial
        "joboolo.fr",
        "/%2f%2fevil.com",                         # '//' caché après décodage
        "%2f%2fevil.com",
        "%252f%252fevil.com",
        "%255cevil",                               # backslash caché
        "%0d%0aLocation: https://evil.example",    # CR/LF encodés
        "%250d%250aX-Evil: 1",
        "%2568%2574%2574%2570:%252F%252Fevil.com", # schéma révélé par décodage
        "%00evil",
        "\u0085evil",                              # NEL (contrôle C1)
        "\u000bevil",                              # tabulation verticale
        "\u00a0evil",                              # NBSP trompeur en tête
    ])
    def test_attack_matrix_refused(self, target):
        assert _refuses(target), f"devrait être refusé: {target!r}"


class TestAppUrlVariants:
    def test_custom_port_same_origin_allowed(self):
        app = "http://localhost:8000"
        assert safe_urls.safe_redirect("http://localhost:8000/jobs/1", app) == "http://localhost:8000/jobs/1"

    def test_custom_port_other_port_refused(self):
        app = "http://localhost:8000"
        assert _refuses("http://localhost/jobs/1", app)       # port 80 != 8000
        assert _refuses("https://localhost:8000/", app)       # schéma différent
        assert _refuses("http://localhost:8001/", app)

    def test_ipv6_same_origin_allowed(self):
        app = "http://[::1]:8000"
        assert safe_urls.safe_redirect("http://[::1]:8000/x", app) == "http://[::1]:8000/x"

    def test_invalid_app_url_only_relatives_allowed(self):
        for bad in ("not-a-url", "", "https://"):
            assert safe_urls.safe_redirect("/jobs/123", bad) == "/jobs/123"
            assert _refuses("https://joboolo.fr/x", bad)

    def test_http_app_http_target_allowed(self):
        app = "http://joboolo.fr"
        assert safe_urls.safe_redirect("http://joboolo.fr/jobs/1", app) == "http://joboolo.fr/jobs/1"
        assert _refuses("https://joboolo.fr/jobs/1", app)


class TestTrackedRoundTrip:
    def _decoded_redirect(self, tracked_url):
        query = urlsplit(tracked_url).query
        values = parse_qs(query)
        assert "redirect" in values
        return values["redirect"][0]

    def test_job_link_round_trip(self):
        target = f"{APP}/jobs/job_123"
        tracked = _tracked(APP, "alert_1", target)
        assert safe_urls.safe_redirect(self._decoded_redirect(tracked), APP) == target

    def test_all_offers_link_round_trip(self):
        tracked = _tracked(APP, "alert_1", APP)
        assert safe_urls.safe_redirect(self._decoded_redirect(tracked), APP) == APP

    def test_encoded_target_round_trip(self):
        target = f"{APP}/jobs/%E2%82%AC"
        tracked = _tracked(APP, "alert_1", target)
        decoded = self._decoded_redirect(tracked)
        assert _refuses(decoded, APP) is False
        assert safe_urls.safe_redirect(decoded, APP) == decoded

    def test_without_alert_id_untracked(self):
        assert _tracked(APP, "", f"{APP}/jobs/1") == f"{APP}/jobs/1"


# --------------------------------------------------------------------------
# Handler : tracking toujours effectué + destination sûre
# --------------------------------------------------------------------------

def _install_alerts_stubs(monkeypatch):
    """Stubs minimaux pour charger routes/alerts.py sans DB/Mongo ni auth.

    `fastapi` reste le vrai package : le handler produit un vrai
    RedirectResponse dont on lit l'en-tête Location.
    """
    database = types.ModuleType("database")
    database.get_database = lambda: None
    monkeypatch.setitem(sys.modules, "database", database)

    auth = types.ModuleType("auth")
    auth.get_current_active_user = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "auth", auth)

    scheduler = types.ModuleType("scheduler")
    scheduler.APP_URL = APP
    scheduler._build_job_query = lambda *a, **k: {}
    monkeypatch.setitem(sys.modules, "scheduler", scheduler)

    spec = importlib.util.spec_from_file_location(
        "p008_alerts", BACKEND_DIR / "routes" / "alerts.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "p008_alerts", module)
    spec.loader.exec_module(module)
    return module


def _make_fake_db(alert):
    class _Collection:
        def __init__(self):
            self.calls = []

        async def find_one(self, *a, **k):
            return alert

        async def update_one(self, *a, **k):
            self.calls.append((a, k))
            return None

    db = types.SimpleNamespace(alerts=_Collection(), users=_Collection())
    return db


@pytest.fixture
def alerts_module(monkeypatch):
    """Charge routes/alerts.py avec des stubs ; chaque test patche get_database."""
    return _install_alerts_stubs(monkeypatch)


def _run(coro_fn, *args, **kwargs):
    return asyncio.run(coro_fn(*args, **kwargs))


class TestTrackHandler:
    def test_invalid_destination_falls_back_to_root_and_tracks(self, alerts_module, monkeypatch):
        db = _make_fake_db({"_id": "alert_1", "user_id": "user_1"})

        async def _get_db():
            return db

        monkeypatch.setattr(alerts_module, "get_database", _get_db)

        resp = _run(alerts_module.track_alert_click, "alert_1", "https://evil.example")
        assert resp.headers["location"] == "/"
        assert db.alerts.calls     # last_viewed_at + click_count mis à jour
        assert db.users.calls      # user_id présent => maj user

    def test_invalid_encoded_destination_tracks_and_fallbacks(self, alerts_module, monkeypatch):
        db = _make_fake_db({"_id": "alert_1", "user_id": "user_1"})

        async def _get_db():
            return db

        monkeypatch.setattr(alerts_module, "get_database", _get_db)

        resp = _run(alerts_module.track_alert_click, "alert_1", "%2f%2fevil.com")
        assert resp.headers["location"] == "/"
        assert db.alerts.calls and db.users.calls

    def test_same_origin_absolute_kept_and_tracks(self, alerts_module, monkeypatch):
        db = _make_fake_db({"_id": "alert_1", "user_id": "user_1"})

        async def _get_db():
            return db

        monkeypatch.setattr(alerts_module, "get_database", _get_db)

        resp = _run(alerts_module.track_alert_click, "alert_1", f"{APP}/jobs/123")
        assert resp.headers["location"] == f"{APP}/jobs/123"
        assert db.alerts.calls and db.users.calls

    def test_safe_relative_kept_and_tracks(self, alerts_module, monkeypatch):
        db = _make_fake_db({"_id": "alert_1", "user_id": "user_1"})

        async def _get_db():
            return db

        monkeypatch.setattr(alerts_module, "get_database", _get_db)

        resp = _run(alerts_module.track_alert_click, "alert_1", "/jobs/123")
        assert resp.headers["location"] == "/jobs/123"
        assert db.alerts.calls and db.users.calls

    def test_empty_redirect_tracks_and_goes_to_root(self, alerts_module, monkeypatch):
        db = _make_fake_db({"_id": "alert_1", "user_id": None})

        async def _get_db():
            return db

        monkeypatch.setattr(alerts_module, "get_database", _get_db)

        resp = _run(alerts_module.track_alert_click, "alert_1", "")
        assert resp.headers["location"] == "/"
        assert db.alerts.calls
        assert not db.users.calls  # pas de user_id => pas de maj user

    def test_unknown_alert_no_tracking_still_safe_destination(self, alerts_module, monkeypatch):
        db = _make_fake_db(None)

        async def _get_db():
            return db

        monkeypatch.setattr(alerts_module, "get_database", _get_db)

        resp = _run(alerts_module.track_alert_click, "unknown", "//evil.example")
        assert resp.headers["location"] == "/"
        assert not db.alerts.calls and not db.users.calls

    def test_tracking_fields_set(self, alerts_module, monkeypatch):
        alert = {"_id": "alert_1", "user_id": "user_1"}
        db = _make_fake_db(alert)

        async def _get_db():
            return db

        monkeypatch.setattr(alerts_module, "get_database", _get_db)

        _run(alerts_module.track_alert_click, "alert_1", "https://evil.example")
        assert db.alerts.calls
        args, _ = db.alerts.calls[0]
        assert args[0] == {"_id": "alert_1"}
        assert args[1]["$set"]["last_viewed_at"] <= datetime.utcnow()
        assert args[1]["$inc"] == {"click_count": 1}
        user_args, _ = db.users.calls[0]
        assert user_args[1]["$set"]["last_alert_viewed_at"] <= datetime.utcnow()