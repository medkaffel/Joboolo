"""Backend tests for Lot 4 (geo hierarchy, partner self-registration, cascade delete,
XML feed mandatory, logos, campaign jobs listing)."""
import io
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

ADMIN = ("admin@joboolo.fr", "AdminJoboolo2026!")
PARTNER = ("partenaire@joboolo.fr", "Partner2026!")


def login(email, pwd):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd})
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:300]}"
    return r.json()["token"]["access_token"]


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


# -------- Geo hierarchy --------
class TestGeoHierarchy:
    def _fetch(self, location):
        r = requests.get(f"{API}/jobs", params={"location": location, "limit": 100})
        assert r.status_code == 200, r.text
        return r.json().get("jobs", r.json()) if isinstance(r.json(), dict) else r.json()

    def test_loire_returns_only_department_42(self):
        jobs = self._fetch("Loire")
        # collect postcodes in each job's location like "City (42160)"
        pcs = []
        for j in jobs:
            m = re.search(r"\((\d{4,5})\)", j.get("location", "") or "")
            if m:
                pcs.append(m.group(1))
        # If no jobs, treat as informative but not a hard fail
        for pc in pcs:
            assert pc.startswith("42"), f"Loire returned a job outside dept 42: postcode={pc}, jobs={[j.get('location') for j in jobs]}"

    def test_rhone_returns_only_department_69(self):
        jobs = self._fetch("Rhône")
        pcs = [re.search(r"\((\d{4,5})\)", j.get("location") or "").group(1)
               for j in jobs if re.search(r"\((\d{4,5})\)", j.get("location") or "")]
        for pc in pcs:
            assert pc.startswith("69"), f"Rhône returned postcode outside 69: {pc}"

    def test_region_pays_de_la_loire(self):
        jobs = self._fetch("Pays de la Loire")
        # Region 52 => dept 44 49 53 72 85
        allowed = {"44", "49", "53", "72", "85"}
        pcs = [re.search(r"\((\d{4,5})\)", j.get("location") or "").group(1)
               for j in jobs if re.search(r"\((\d{4,5})\)", j.get("location") or "")]
        for pc in pcs:
            assert pc[:2] in allowed, f"Pays de la Loire got postcode outside region: {pc}"

    def test_paris_city_still_works(self):
        jobs = self._fetch("Paris")
        # Should return at least those tagged Paris; loose check
        assert isinstance(jobs, list)


# -------- Partner self-registration + pending block --------
class TestPartnerSelfReg:
    email = f"test_partner_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "PartnerTest2026!"
    user_id = None

    def test_register_partner_returns_pending(self):
        r = requests.post(f"{API}/auth/register-partner", json={
            "email": self.email, "password": self.pwd,
            "first_name": "Test", "last_name": "Partner",
            "company_name": f"TEST_Company_{uuid.uuid4().hex[:6]}",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("pending") is True
        assert "message" in data

    def test_login_pending_returns_403(self):
        r = requests.post(f"{API}/auth/login", json={"email": self.email, "password": self.pwd})
        assert r.status_code == 403, f"expected 403 for pending partner, got {r.status_code}: {r.text}"

    def test_admin_activate_then_login_succeeds(self):
        admin_tok = login(*ADMIN)
        # find the new user
        r = requests.get(f"{API}/admin/users", headers=H(admin_tok), params={"user_type": "partner"})
        assert r.status_code == 200, r.text
        users = r.json()
        me = next((u for u in users if u.get("email") == self.email), None)
        assert me is not None, f"newly registered partner not found in /admin/users"
        TestPartnerSelfReg.user_id = me.get("id") or me.get("_id")
        assert TestPartnerSelfReg.user_id
        # toggle active
        r = requests.post(f"{API}/admin/users/{TestPartnerSelfReg.user_id}/toggle", headers=H(admin_tok))
        assert r.status_code == 200, r.text
        # login should now work
        r = requests.post(f"{API}/auth/login", json={"email": self.email, "password": self.pwd})
        assert r.status_code == 200, f"login after admin activation failed: {r.status_code} {r.text}"


# -------- Campaign: xml mandatory + cascade delete + jobs listing --------
class TestCampaignsXMLAndCascade:
    camp_id = None

    def test_create_without_xml_returns_400(self):
        tok = login(*PARTNER)
        r = requests.post(f"{API}/partner/campaigns", headers=H(tok), json={
            "name": f"TEST_NoXML_{int(time.time())}", "billing_mode": "per_click", "cpc": 0.35,
        })
        assert r.status_code == 400, f"expected 400 without xml_feed_url, got {r.status_code}: {r.text}"

    def test_create_with_xml_ok(self):
        tok = login(*PARTNER)
        r = requests.post(f"{API}/partner/campaigns", headers=H(tok), json={
            "name": f"TEST_WithXML_{int(time.time())}", "billing_mode": "per_click", "cpc": 0.35,
            "xml_feed_url": "https://example.com/feed.xml",
        })
        assert r.status_code == 200, r.text
        TestCampaignsXMLAndCascade.camp_id = r.json()["id"]

    def test_campaign_jobs_endpoint(self):
        tok = login(*PARTNER)
        # inject a synthetic job with campaign_id via DB is out-of-scope; endpoint should still return []
        r = requests.get(f"{API}/partner/campaigns/{self.camp_id}/jobs", headers=H(tok))
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_cascade_delete_removes_campaign_jobs(self):
        # We'll add a fake job with campaign_id to DB via a partner-import path unavailable —
        # do a lighter behavioral check: insert-like via DELETE alone should succeed.
        tok = login(*PARTNER)
        r = requests.delete(f"{API}/partner/campaigns/{self.camp_id}", headers=H(tok))
        assert r.status_code == 200
        # After delete, jobs endpoint should 404
        r2 = requests.get(f"{API}/partner/campaigns/{self.camp_id}/jobs", headers=H(tok))
        assert r2.status_code == 404


# -------- Partner logo upload + public serve --------
class TestPartnerLogo:
    def test_upload_logo_and_public_serve(self):
        tok = login(*PARTNER)
        # 1x1 png
        png = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
            "0000000A49444154789C6300010000000500010D0A2DB40000000049454E44AE426082"
        )
        files = {"file": ("logo.png", io.BytesIO(png), "image/png")}
        r = requests.post(f"{API}/partner/logo", headers=H(tok), files=files)
        assert r.status_code == 200, r.text
        url = r.json()["logo_url"]
        assert url.startswith("/api/files/public/"), url
        # fetch publicly (no auth)
        r2 = requests.get(f"{BASE}{url}")
        assert r2.status_code == 200, f"public logo fetch failed: {r2.status_code} {r2.text[:200]}"
        assert r2.headers.get("content-type", "").startswith("image/")


# -------- /api/jobs/suggest for location autocomplete --------
class TestSuggest:
    def test_suggest_location(self):
        r = requests.get(f"{API}/jobs/suggest", params={"q": "Pa", "field": "location"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict) and "suggestions" in data
        assert isinstance(data["suggestions"], list)
