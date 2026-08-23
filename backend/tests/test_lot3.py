"""Lot 3 (Monétisation & partenaires) backend tests.
Covers: admin general settings, xml-feeds CRUD, admin alerts,
partner campaigns CRUD (per_click + per_posting)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@joboolo.fr", "password": "AdminJoboolo2026!"}
PARTNER = {"email": "partenaire@joboolo.fr", "password": "Partner2026!"}
POST_PARTNER = {"email": "posting@joboolo.fr", "password": "Post2026!"}


def _login(creds):
    r = requests.post(f"{API}/auth/login", json=creds)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text}"
    return r.json()["token"]["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN)


@pytest.fixture(scope="module")
def partner_token():
    return _login(PARTNER)


@pytest.fixture(scope="module")
def posting_partner_token():
    return _login(POST_PARTNER)


# ---------- Admin general settings ----------
class TestAdminSettings:
    def test_get_settings(self, admin_token):
        r = requests.get(f"{API}/admin/settings", headers=_h(admin_token))
        assert r.status_code == 200, r.text
        d = r.json()
        assert "pack_validity_days" in d
        assert "low_balance_threshold" in d

    def test_update_settings_persists(self, admin_token):
        # update
        r = requests.put(f"{API}/admin/settings", headers=_h(admin_token),
                         json={"pack_validity_days": 45, "low_balance_threshold": 15.0})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["pack_validity_days"] == 45
        assert float(d["low_balance_threshold"]) == 15.0

        # re-read
        r2 = requests.get(f"{API}/admin/settings", headers=_h(admin_token))
        assert r2.json()["pack_validity_days"] == 45

        # restore default 30
        r3 = requests.put(f"{API}/admin/settings", headers=_h(admin_token),
                          json={"pack_validity_days": 30, "low_balance_threshold": 10.0})
        assert r3.status_code == 200
        assert r3.json()["pack_validity_days"] == 30


# ---------- Admin XML feeds ----------
class TestXmlFeeds:
    _feed_id = None
    _feed_id_existing = None

    def test_create_feed_with_new_partner(self, admin_token):
        name = f"TEST_Feed_{int(time.time())}"
        r = requests.post(f"{API}/admin/xml-feeds", headers=_h(admin_token), json={
            "source_name": name,
            "url": "https://example.com/jobs.xml",
            "billing_mode": "per_click",
            "cpc": 0.25,
            "new_partner_company": f"TEST_Company_{int(time.time())}",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source_name"] == name
        assert d["partner_id"]
        assert d["company_name"].startswith("TEST_Company_")
        TestXmlFeeds._feed_id = d["id"]

    def test_list_feeds_shows_created(self, admin_token):
        r = requests.get(f"{API}/admin/xml-feeds", headers=_h(admin_token))
        assert r.status_code == 200
        assert any(f["id"] == TestXmlFeeds._feed_id for f in r.json())

    def test_create_feed_with_existing_partner(self, admin_token):
        # find partenaire@joboolo.fr partner id
        r = requests.get(f"{API}/admin/partners", headers=_h(admin_token))
        assert r.status_code == 200
        partners = r.json()
        target = next(p for p in partners if p["email"] == "partenaire@joboolo.fr")
        pid = target["id"]

        r = requests.post(f"{API}/admin/xml-feeds", headers=_h(admin_token), json={
            "source_name": f"TEST_ExistFeed_{int(time.time())}",
            "url": "https://example.com/jobs2.xml",
            "billing_mode": "per_click",
            "cpc": 0.3,
            "partner_id": pid,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["partner_id"] == pid
        TestXmlFeeds._feed_id_existing = d["id"]

    def test_import_feed_returns_result(self, admin_token):
        # example.com URL will fail — that's acceptable, just verify endpoint responds
        fid = TestXmlFeeds._feed_id
        r = requests.post(f"{API}/admin/xml-feeds/{fid}/import", headers=_h(admin_token))
        # Import should return 200 with an error result, or fail with 4xx/5xx
        assert r.status_code in [200, 400, 500, 502], f"unexpected {r.status_code}: {r.text}"

    def test_delete_feed(self, admin_token):
        for fid in [TestXmlFeeds._feed_id, TestXmlFeeds._feed_id_existing]:
            if not fid:
                continue
            r = requests.delete(f"{API}/admin/xml-feeds/{fid}", headers=_h(admin_token))
            assert r.status_code == 200


# ---------- Admin alerts ----------
class TestAdminAlerts:
    _alert_id = None

    @pytest.fixture(scope="class", autouse=True)
    def _seed_alert(self, request):
        # Seed one alert via a candidate account so admin has something to toggle/delete
        rc = requests.post(f"{API}/auth/login", json={"email": "candidate@joboolo.fr", "password": "Test1234"})
        assert rc.status_code == 200
        tok = rc.json()["token"]["access_token"]
        r = requests.post(f"{API}/alerts", headers=_h(tok),
                          json={"search": "TEST_lot3", "location": "Paris", "frequency": "daily"})
        assert r.status_code == 200
        TestAdminAlerts._alert_id = r.json()["id"]
        yield
        # best-effort cleanup (may already be deleted by test)
        requests.delete(f"{API}/alerts/{TestAdminAlerts._alert_id}", headers=_h(tok))

    def test_list_alerts(self, admin_token):
        r = requests.get(f"{API}/admin/alerts", headers=_h(admin_token))
        assert r.status_code == 200, r.text
        assert any(a["id"] == TestAdminAlerts._alert_id for a in r.json())

    def test_filter_active(self, admin_token):
        r = requests.get(f"{API}/admin/alerts", headers=_h(admin_token), params={"active": "true"})
        assert r.status_code == 200
        for a in r.json():
            assert a["is_active"] is True

    def test_toggle_alert(self, admin_token):
        aid = TestAdminAlerts._alert_id
        r = requests.put(f"{API}/admin/alerts/{aid}/toggle", headers=_h(admin_token))
        assert r.status_code == 200
        first = r.json()["is_active"]
        r2 = requests.put(f"{API}/admin/alerts/{aid}/toggle", headers=_h(admin_token))
        assert r2.json()["is_active"] is not first

    def test_delete_alert(self, admin_token):
        aid = TestAdminAlerts._alert_id
        r = requests.delete(f"{API}/admin/alerts/{aid}", headers=_h(admin_token))
        assert r.status_code == 200
        # verify gone
        r2 = requests.get(f"{API}/admin/alerts", headers=_h(admin_token))
        assert not any(a["id"] == aid for a in r2.json())


# ---------- Partner campaigns ----------
class TestPartnerCampaigns:
    _campaign_id_click = None
    _campaign_id_posting = None

    def test_create_per_click_campaign(self, partner_token):
        r = requests.post(f"{API}/partner/campaigns", headers=_h(partner_token), json={
            "name": f"TEST_Camp_Click_{int(time.time())}",
            "billing_mode": "per_click",
            "cpc": 0.35, "cpc_max": 0.60, "budget_limit": 500.0,
            "start_date": "2026-07-01", "end_date": "2026-08-01",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["billing_mode"] == "per_click"
        assert d["cpc"] == 0.35
        assert d["cpc_max"] == 0.60
        assert d["budget_limit"] == 500.0
        assert d["status"] == "active"
        TestPartnerCampaigns._campaign_id_click = d["id"]

    def test_create_per_posting_uses_settings_validity(self, posting_partner_token, admin_token):
        # ensure settings validity is 30
        requests.put(f"{API}/admin/settings", headers=_h(admin_token),
                     json={"pack_validity_days": 30, "low_balance_threshold": 10.0})
        r = requests.post(f"{API}/partner/campaigns", headers=_h(posting_partner_token), json={
            "name": f"TEST_Camp_Post_{int(time.time())}",
            "billing_mode": "per_posting",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["billing_mode"] == "per_posting"
        assert d["validity_days"] == 30
        assert d["cpc"] is None
        assert d["budget_limit"] is None
        TestPartnerCampaigns._campaign_id_posting = d["id"]

    def test_list_campaigns(self, partner_token):
        r = requests.get(f"{API}/partner/campaigns", headers=_h(partner_token))
        assert r.status_code == 200
        assert any(c["id"] == TestPartnerCampaigns._campaign_id_click for c in r.json())

    def test_toggle_campaign_status(self, partner_token):
        cid = TestPartnerCampaigns._campaign_id_click
        r = requests.put(f"{API}/partner/campaigns/{cid}", headers=_h(partner_token),
                         json={"status": "paused"})
        assert r.status_code == 200
        assert r.json()["status"] == "paused"

        r2 = requests.put(f"{API}/partner/campaigns/{cid}", headers=_h(partner_token),
                          json={"status": "active"})
        assert r2.json()["status"] == "active"

    def test_delete_campaigns(self, partner_token, posting_partner_token):
        r = requests.delete(f"{API}/partner/campaigns/{TestPartnerCampaigns._campaign_id_click}",
                            headers=_h(partner_token))
        assert r.status_code == 200
        r2 = requests.delete(f"{API}/partner/campaigns/{TestPartnerCampaigns._campaign_id_posting}",
                             headers=_h(posting_partner_token))
        assert r2.status_code == 200
