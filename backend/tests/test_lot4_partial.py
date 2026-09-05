"""Backend tests for Lot 4 partial: geo detect, radius search, impressions dedup,
signup provenance tracking."""
import os
import re
import time
import uuid
import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
API = f"{BASE}/api"

# E2E credentials must come from environment — no repository fallbacks
ADMIN_EMAIL = os.environ.get("E2E_ADMIN_EMAIL", "admin@joboolo.fr")
ADMIN_PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD")
PARTNER_EMAIL = os.environ.get("E2E_PARTNER_EMAIL", "partenaire@joboolo.fr")
PARTNER_PASSWORD = os.environ.get("E2E_PARTNER_PASSWORD")


def login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd})
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]["access_token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    if not ADMIN_PASSWORD:
        pytest.skip("E2E_ADMIN_PASSWORD not set")
    return login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="module")
def partner_token():
    if not PARTNER_PASSWORD:
        pytest.skip("E2E_PARTNER_PASSWORD not set")
    return login(PARTNER_EMAIL, PARTNER_PASSWORD)


# -------- IP geo detect --------
class TestGeoDetect:
    def test_detect_returns_json_shape(self):
        r = requests.get(f"{API}/geo/detect")
        assert r.status_code == 200, r.text
        data = r.json()
        for key in ("country", "country_code", "region", "city"):
            assert key in data, f"missing key {key}: {data}"


# -------- Radius search --------
class TestRadiusSearch:
    def _fetch(self, params):
        r = requests.get(f"{API}/jobs", params=params)
        assert r.status_code == 200, r.text
        return r.json()

    def test_lyon_radius_10_all_dept_69(self):
        data = self._fetch({"location": "Lyon", "radius": 10, "limit": 100})
        jobs = data.get("jobs", [])
        pcs = [re.search(r"\((\d{4,5})\)", j.get("location") or "").group(1)
               for j in jobs if re.search(r"\((\d{4,5})\)", j.get("location") or "")]
        for pc in pcs:
            assert pc.startswith("69"), f"Lyon radius 10 returned postcode outside 69: {pc}"
        assert len(jobs) > 0, "Lyon radius=10 should return some jobs"

    def test_radius_5_smaller_than_100(self):
        d5 = self._fetch({"location": "Lyon", "radius": 5, "limit": 100})
        d100 = self._fetch({"location": "Lyon", "radius": 100, "limit": 100})
        assert d5["total"] <= d100["total"], f"radius=5 total {d5['total']} should <= radius=100 total {d100['total']}"


# -------- Impressions --------
class TestImpressions:
    def test_impressions_recorded_only_for_partner_jobs(self):
        r = requests.get(f"{API}/jobs", params={"limit": 50})
        jobs = r.json().get("jobs", [])
        partner_ids = [j["id"] for j in jobs if j.get("is_partner")]
        non_partner_ids = [j["id"] for j in jobs if not j.get("is_partner")][:2]
        if not partner_ids:
            pytest.skip("No partner jobs to test impressions")
        # Send mix
        payload = {"job_ids": partner_ids[:3] + non_partner_ids}
        r = requests.post(f"{API}/jobs/impressions", json=payload)
        assert r.status_code == 200, r.text
        recorded = r.json().get("recorded")
        assert recorded == len(partner_ids[:3]), \
            f"expected only partner impressions recorded ({len(partner_ids[:3])}), got {recorded}"

    def test_empty_payload(self):
        r = requests.post(f"{API}/jobs/impressions", json={"job_ids": []})
        assert r.status_code == 200
        assert r.json()["recorded"] == 0

    def test_partner_performance_has_impressions(self, partner_token):
        r = requests.get(f"{API}/partner/performance", headers=H(partner_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "totals" in data
        assert "impressions" in data["totals"], f"totals missing impressions: {data['totals']}"
        assert "ctr" in data["totals"]


# -------- Signup provenance tracking --------
class TestProvenance:
    email = f"test_prov_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "TestProv2026!"
    user_id = None

    def test_register_with_provenance(self):
        payload = {
            "email": self.email,
            "password": self.pwd,
            "first_name": "Prov",
            "last_name": "Tester",
            "user_type": "candidate",
            "signup_source": "google",
            "signup_referrer": "https://google.com/search",
            "signup_landing": "/?q=job",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "spring2026",
        }
        r = requests.post(f"{API}/auth/register", json=payload)
        assert r.status_code == 200, f"register: {r.status_code} {r.text[:300]}"

    def test_admin_sees_provenance(self, admin_token):
        r = requests.get(f"{API}/admin/users", headers=H(admin_token), params={"user_type": "candidate"})
        assert r.status_code == 200
        users = r.json()
        me = next((u for u in users if u.get("email") == self.email), None)
        assert me is not None, "newly registered user not found"
        TestProvenance.user_id = me.get("id") or me.get("_id")
        # Provenance fields present
        has_source = me.get("signup_source") or me.get("source") or (me.get("provenance") or {}).get("source")
        assert has_source, f"provenance/signup_source missing on admin user record: {list(me.keys())}"

    def test_cleanup(self, admin_token):
        if not TestProvenance.user_id:
            return
        r = requests.delete(f"{API}/admin/users/{TestProvenance.user_id}", headers=H(admin_token))
        assert r.status_code in (200, 204, 404)
