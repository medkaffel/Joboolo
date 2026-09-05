"""Tests for the Recruiter premium landing feature: /api/recruiter/* and Stripe regression."""
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)
API = f"{BASE_URL}/api"

# E2E credentials must come from environment — no repository fallbacks
EMPLOYER_EMAIL = os.environ.get("E2E_EMPLOYER_EMAIL", "recruteur@techcorp.fr")
EMPLOYER_PASSWORD = os.environ.get("E2E_EMPLOYER_PASSWORD")
CANDIDATE_EMAIL = os.environ.get("E2E_CANDIDATE_EMAIL", "candidate@test.fr")
CANDIDATE_PASSWORD = os.environ.get("E2E_CANDIDATE_PASSWORD")
ADMIN_EMAIL = os.environ.get("E2E_ADMIN_EMAIL", "admin@joboolo.fr")
ADMIN_PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD")
PARTNER_EMAIL = os.environ.get("E2E_PARTNER_EMAIL", "partenaire@joboolo.fr")
PARTNER_PASSWORD = os.environ.get("E2E_PARTNER_PASSWORD")

EMPLOYER = (EMPLOYER_EMAIL, EMPLOYER_PASSWORD, "employer")
CANDIDATE = (CANDIDATE_EMAIL, CANDIDATE_PASSWORD, "candidate")
ADMIN = (ADMIN_EMAIL, ADMIN_PASSWORD, "admin")
PARTNER = (PARTNER_EMAIL, PARTNER_PASSWORD, "partner")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(client, creds):
    email, password, utype = creds
    r = client.post(f"{API}/auth/login", json={
        "email": email, "password": password, "expected_user_type": utype
    })
    if r.status_code != 200:
        pytest.fail(f"Login failed for {email}: {r.status_code} {r.text[:300]}")
    body = r.json()
    tok = body.get("token")
    token = tok.get("access_token") if isinstance(tok, dict) else (tok or body.get("access_token"))
    assert token, f"No token in login response: {r.text[:300]}"
    return token


@pytest.fixture(scope="module")
def employer_token(client):
    if not EMPLOYER_PASSWORD:
        pytest.skip("E2E_EMPLOYER_PASSWORD not set")
    return _login(client, EMPLOYER)


@pytest.fixture(scope="module")
def candidate_token(client):
    if not CANDIDATE_PASSWORD:
        pytest.skip("E2E_CANDIDATE_PASSWORD not set")
    return _login(client, CANDIDATE)


@pytest.fixture(scope="module")
def admin_token(client):
    if not ADMIN_PASSWORD:
        pytest.skip("E2E_ADMIN_PASSWORD not set")
    return _login(client, ADMIN)


# ---------- GET /api/recruiter/packs ----------
class TestRecruiterPacks:
    def test_packs_public(self, client):
        r = client.get(f"{API}/recruiter/packs")
        assert r.status_code == 200, r.text[:300]
        packs = r.json()["packs"]
        assert len(packs) == 3
        by_id = {p["id"]: p for p in packs}
        assert by_id["premium_1"]["price"] == 299 and by_id["premium_1"]["postings"] == 1
        assert by_id["premium_3"]["price"] == 799 and by_id["premium_3"]["postings"] == 3
        assert by_id["premium_5"]["price"] == 1199 and by_id["premium_5"]["postings"] == 5
        for p in packs:
            assert isinstance(p["label"], str) and p["label"]


# ---------- POST /api/recruiter/quote ----------
class TestRecruiterQuote:
    def test_quote_success_and_persistence(self, client, admin_token):
        payload = {
            "first_name": "TEST_Marie", "last_name": "TEST_Dupont",
            "company": "TEST_QA Corp", "email": "test_qa_quote@example.com",
            "phone": "0612345678", "message": "TEST besoin urgent", "need": "targeted",
        }
        r = client.post(f"{API}/recruiter/quote", json=payload)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        assert data["success"] is True
        assert isinstance(data.get("message"), str) and data["message"]

        # verify persisted via admin listing
        lr = requests.get(f"{API}/recruiter/quotes", headers={"Authorization": f"Bearer {admin_token}"})
        assert lr.status_code == 200, lr.text[:300]
        leads = lr.json()
        assert any(l["email"] == payload["email"] and l["company"] == "TEST_QA Corp"
                   and l["need"] == "targeted" for l in leads), "Quote not persisted"
        # no mongo _id leak
        assert all("_id" not in l for l in leads)

    def test_quote_minimal_fields(self, client):
        r = client.post(f"{API}/recruiter/quote", json={
            "first_name": "TEST_A", "last_name": "TEST_B",
            "company": "TEST_Min", "email": "test_qa_min@example.com",
        })
        assert r.status_code == 200, r.text[:300]
        assert r.json()["success"] is True

    def test_quote_invalid_email(self, client):
        r = client.post(f"{API}/recruiter/quote", json={
            "first_name": "TEST_A", "last_name": "TEST_B",
            "company": "TEST_Bad", "email": "not-an-email",
        })
        assert r.status_code == 422, f"expected 422 got {r.status_code}"

    def test_quote_missing_fields(self, client):
        r = client.post(f"{API}/recruiter/quote", json={"email": "test_qa@example.com"})
        assert r.status_code == 422

    def test_quotes_list_requires_admin(self, client, employer_token):
        r = requests.get(f"{API}/recruiter/quotes", headers={"Authorization": f"Bearer {employer_token}"})
        assert r.status_code == 403, f"expected 403 got {r.status_code}"

    def test_quotes_list_requires_auth(self, client):
        r = requests.get(f"{API}/recruiter/quotes")
        assert r.status_code in (401, 403)


# ---------- POST /api/recruiter/checkout (Stripe) ----------
class TestRecruiterCheckout:
    def test_checkout_requires_auth(self):
        r = requests.post(f"{API}/recruiter/checkout", json={"pack_id": "premium_1", "origin_url": BASE_URL})
        assert r.status_code in (401, 403)

    def test_checkout_rejects_candidate(self, candidate_token):
        r = requests.post(f"{API}/recruiter/checkout",
                          json={"pack_id": "premium_1", "origin_url": BASE_URL},
                          headers={"Authorization": f"Bearer {candidate_token}"})
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"

    def test_checkout_invalid_pack(self, employer_token):
        r = requests.post(f"{API}/recruiter/checkout",
                          json={"pack_id": "bogus", "origin_url": BASE_URL},
                          headers={"Authorization": f"Bearer {employer_token}"})
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"

    @pytest.mark.parametrize("pack_id", ["premium_1", "premium_3", "premium_5"])
    def test_checkout_returns_stripe_url(self, employer_token, pack_id):
        r = requests.post(f"{API}/recruiter/checkout",
                          json={"pack_id": pack_id, "origin_url": BASE_URL},
                          headers={"Authorization": f"Bearer {employer_token}"})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        data = r.json()
        assert "checkout_url" in data and "session_id" in data
        assert "checkout.stripe.com" in data["checkout_url"], data["checkout_url"]
        assert data["session_id"].startswith("cs_")

    def test_payment_status_after_checkout(self, employer_token):
        r = requests.post(f"{API}/recruiter/checkout",
                          json={"pack_id": "premium_3", "origin_url": BASE_URL},
                          headers={"Authorization": f"Bearer {employer_token}"})
        assert r.status_code == 200, r.text[:300]
        sid = r.json()["session_id"]
        sr = requests.get(f"{API}/payments/status/{sid}",
                          headers={"Authorization": f"Bearer {employer_token}"})
        assert sr.status_code == 200, f"{sr.status_code}: {sr.text[:300]}"
        s = sr.json()
        assert s.get("kind") == "recruiter_pack", s
        assert s.get("postings") == 3, s
        assert s.get("payment_status") in ("unpaid", "pending", "no_payment_required")


# ---------- Regression: partner top-up Stripe flow ----------
class TestPartnerTopupRegression:
    def test_partner_topup_creates_stripe_session_as_admin(self, client, admin_token):
        """Documented partner logins no longer exist in DB, so exercise the admin path."""
        h = {"Authorization": f"Bearer {admin_token}"}
        pr = requests.get(f"{API}/admin/partners", headers=h)
        assert pr.status_code == 200, f"{pr.status_code}: {pr.text[:300]}"
        partners = pr.json()
        partners = partners.get("partners", partners) if isinstance(partners, dict) else partners
        assert partners, "No partners available to test top-up"
        pid = partners[0].get("user_id") or partners[0].get("id")
        r = requests.post(f"{API}/payments/create-topup",
                          json={"amount": 50.0, "origin_url": BASE_URL, "partner_id": pid},
                          headers=h)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        data = r.json()
        url = data.get("checkout_url") or data.get("url")
        assert url and "checkout.stripe.com" in url, data
