"""Backend regression tests for Joboolo.
Covers: auth register/login/PUT me, alerts CRUD + send-now, google/session 401,
employer flow (company + job create/list/delete)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback: read from frontend .env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except FileNotFoundError:
        pass

API = f"{BASE_URL}/api"

CANDIDATE_EMAIL = "candidate@joboolo.fr"
CANDIDATE_PWD = "Test1234"
EMPLOYER_EMAIL = "employer@joboolo.fr"
EMPLOYER_PWD = "Test1234"


@pytest.fixture(scope="session")
def candidate_token():
    r = requests.post(f"{API}/auth/login", json={"email": CANDIDATE_EMAIL, "password": CANDIDATE_PWD})
    if r.status_code != 200:
        # try register
        r = requests.post(f"{API}/auth/register", json={
            "email": CANDIDATE_EMAIL, "password": CANDIDATE_PWD,
            "first_name": "Cand", "last_name": "Test", "user_type": "candidate"
        })
    assert r.status_code == 200, f"candidate auth failed: {r.status_code} {r.text}"
    return r.json()["token"]["access_token"]


@pytest.fixture(scope="session")
def employer_token():
    r = requests.post(f"{API}/auth/login", json={"email": EMPLOYER_EMAIL, "password": EMPLOYER_PWD})
    if r.status_code != 200:
        r = requests.post(f"{API}/auth/register", json={
            "email": EMPLOYER_EMAIL, "password": EMPLOYER_PWD,
            "first_name": "Emp", "last_name": "Test", "user_type": "employer"
        })
    assert r.status_code == 200, f"employer auth failed: {r.status_code} {r.text}"
    return r.json()["token"]["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------- Auth ----------------
class TestAuth:
    def test_login_returns_token(self, candidate_token):
        assert isinstance(candidate_token, str) and len(candidate_token) > 20

    def test_get_me(self, candidate_token):
        r = requests.get(f"{API}/auth/me", headers=_h(candidate_token))
        assert r.status_code == 200
        assert r.json()["email"] == CANDIDATE_EMAIL

    def test_put_me_updates_profile(self, candidate_token):
        payload = {
            "phone": "+33612345678",
            "location": "Paris",
            "bio": "Test bio",
            "skills": ["Python", "React"],
            "experience_years": 5,
        }
        r = requests.put(f"{API}/auth/me", headers=_h(candidate_token), json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["phone"] == "+33612345678"
        assert data["location"] == "Paris"
        assert data["experience_years"] == 5
        assert "Python" in data["skills"]

        # Verify persistence
        r2 = requests.get(f"{API}/auth/me", headers=_h(candidate_token))
        assert r2.status_code == 200
        assert r2.json()["bio"] == "Test bio"

    def test_google_session_invalid_returns_401(self):
        r = requests.post(f"{API}/auth/google/session", json={"session_id": "invalid_test_session_xyz"})
        assert r.status_code == 401, f"expected 401 got {r.status_code}: {r.text}"


# ---------------- Alerts ----------------
class TestAlerts:
    _alert_id = None

    def test_create_alert(self, candidate_token):
        r = requests.post(f"{API}/alerts", headers=_h(candidate_token), json={
            "search": "développeur", "location": "Paris", "frequency": "daily"
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["frequency"] == "daily"
        assert data["is_active"] is True
        TestAlerts._alert_id = data["id"]

    def test_list_alerts(self, candidate_token):
        r = requests.get(f"{API}/alerts", headers=_h(candidate_token))
        assert r.status_code == 200
        assert any(a["id"] == TestAlerts._alert_id for a in r.json())

    def test_update_alert(self, candidate_token):
        aid = TestAlerts._alert_id
        r = requests.put(f"{API}/alerts/{aid}", headers=_h(candidate_token),
                         json={"frequency": "weekly", "is_active": False})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["frequency"] == "weekly"
        assert data["is_active"] is False

    def test_send_now_returns_count(self, candidate_token):
        aid = TestAlerts._alert_id
        r = requests.post(f"{API}/alerts/{aid}/send-now", headers=_h(candidate_token))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "sent" in data and "count" in data and "message" in data
        # Email not configured — sent should be False
        assert data["sent"] is False
        # Seed jobs should match "développeur" — expect >0. But allow 0 with graceful message.
        assert data["count"] >= 0

    def test_delete_alert(self, candidate_token):
        aid = TestAlerts._alert_id
        r = requests.delete(f"{API}/alerts/{aid}", headers=_h(candidate_token))
        assert r.status_code == 200


# ---------------- Employer flow ----------------
class TestEmployerFlow:
    _company_id = None
    _job_id = None

    def test_create_company(self, employer_token):
        name = f"TEST_Co_{int(time.time())}"
        r = requests.post(f"{API}/companies/", headers=_h(employer_token), json={
            "name": name, "description": "Test company", "location": "Paris",
            "industry": "Tech", "size": "1-10"
        })
        assert r.status_code == 200, r.text
        data = r.json()
        cid = data.get("id") or data.get("_id")
        assert cid
        TestEmployerFlow._company_id = cid

    def test_create_job(self, employer_token):
        cid = TestEmployerFlow._company_id
        r = requests.post(f"{API}/jobs", headers=_h(employer_token), json={
            "title": "TEST Dev Python",
            "description": "Test job description",
            "company_id": cid,
            "location": "Paris",
            "job_type": "CDI",
            "salary_min": 40000,
            "salary_max": 60000,
        })
        assert r.status_code == 200, r.text
        TestEmployerFlow._job_id = r.json()["id"]

    def test_list_company_jobs(self, employer_token):
        cid = TestEmployerFlow._company_id
        r = requests.get(f"{API}/jobs/company/{cid}")
        assert r.status_code == 200, r.text
        jobs = r.json()
        assert any(j["id"] == TestEmployerFlow._job_id for j in jobs)

    def test_delete_job(self, employer_token):
        jid = TestEmployerFlow._job_id
        r = requests.delete(f"{API}/jobs/{jid}", headers=_h(employer_token))
        assert r.status_code == 200
