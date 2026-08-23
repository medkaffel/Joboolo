"""Lot 5 tests: geo autocomplete + employer job management (mine/toggle/edit/hard-delete)."""
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

EMP_EMAIL = "recruteur@techcorp.fr"
EMP_PWD = "password123"
CAND_EMAIL = "candidate@test.fr"
CAND_PWD = "password123"


def _h(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="session")
def emp_token():
    r = requests.post(f"{API}/auth/login", json={"email": EMP_EMAIL, "password": EMP_PWD})
    assert r.status_code == 200, r.text
    return r.json()["token"]["access_token"]


# ---------- Geo autocomplete ----------
class TestGeoAutocomplete:
    def test_bre_returns_bretagne_and_brest(self):
        r = requests.get(f"{API}/geo/autocomplete", params={"q": "bre"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "suggestions" in data
        sugg = data["suggestions"]
        assert isinstance(sugg, list) and len(sugg) > 0
        for s in sugg:
            assert "value" in s and "label" in s and "type" in s
        labels = " | ".join(s["label"] for s in sugg).lower()
        assert "bretagne" in labels, f"missing Bretagne region: {labels}"
        assert "brest" in labels, f"missing Brest: {labels}"

    def test_short_query_returns_empty_or_ok(self):
        r = requests.get(f"{API}/geo/autocomplete", params={"q": "a"})
        assert r.status_code == 200
        assert "suggestions" in r.json()

    def test_paris_returns_city(self):
        r = requests.get(f"{API}/geo/autocomplete", params={"q": "paris"})
        assert r.status_code == 200
        labels = " | ".join(s["label"] for s in r.json()["suggestions"]).lower()
        assert "paris" in labels


# ---------- Employer job management ----------
class TestEmployerJobsMine:
    _created_job_id = None
    _orig_title = None
    _existing_job_id = None
    _orig_active = None

    def test_jobs_mine_requires_employer(self):
        r = requests.get(f"{API}/jobs/mine")
        assert r.status_code in (401, 403)

    def test_jobs_mine_returns_owner_jobs_incl_inactive(self, emp_token):
        r = requests.get(f"{API}/jobs/mine", headers=_h(emp_token))
        assert r.status_code == 200, r.text
        jobs = r.json()
        assert isinstance(jobs, list) and len(jobs) > 0
        # each job has is_active field (may be True or False; endpoint should return both)
        for j in jobs:
            assert "id" in j and "title" in j
            assert "is_active" in j
        TestEmployerJobsMine._existing_job_id = jobs[0]["id"]
        TestEmployerJobsMine._orig_active = jobs[0]["is_active"]
        TestEmployerJobsMine._orig_title = jobs[0]["title"]

    def test_toggle_flips_is_active(self, emp_token):
        jid = TestEmployerJobsMine._existing_job_id
        orig = TestEmployerJobsMine._orig_active
        r = requests.post(f"{API}/jobs/{jid}/toggle", headers=_h(emp_token))
        assert r.status_code == 200, r.text
        # verify via GET mine
        r2 = requests.get(f"{API}/jobs/mine", headers=_h(emp_token))
        job = next(j for j in r2.json() if j["id"] == jid)
        assert job["is_active"] == (not orig)
        # flip back
        requests.post(f"{API}/jobs/{jid}/toggle", headers=_h(emp_token))

    def test_put_job_updates_title(self, emp_token):
        jid = TestEmployerJobsMine._existing_job_id
        new_title = f"TEST Updated {int(time.time())}"
        r = requests.put(f"{API}/jobs/{jid}", headers=_h(emp_token),
                         json={"title": new_title})
        assert r.status_code == 200, r.text
        # verify
        r2 = requests.get(f"{API}/jobs/mine", headers=_h(emp_token))
        job = next(j for j in r2.json() if j["id"] == jid)
        assert job["title"] == new_title
        # restore original
        requests.put(f"{API}/jobs/{jid}", headers=_h(emp_token),
                     json={"title": TestEmployerJobsMine._orig_title})

    def test_create_then_hard_delete(self, emp_token):
        # get a company owned by this employer
        r = requests.get(f"{API}/jobs/mine", headers=_h(emp_token))
        first = r.json()[0]
        cid = first.get("company_id") or (first.get("company") or {}).get("id")
        assert cid, f"no company id: {first}"
        # create
        payload = {
            "title": f"TEST_Lot5_{int(time.time())}",
            "description": "Test job to delete",
            "company_id": cid,
            "location": "Paris",
            "job_type": "CDI",
        }
        r = requests.post(f"{API}/jobs", headers=_h(emp_token), json=payload)
        assert r.status_code == 200, r.text
        jid = r.json()["id"]
        TestEmployerJobsMine._created_job_id = jid
        # hard delete
        r = requests.delete(f"{API}/jobs/{jid}", headers=_h(emp_token))
        assert r.status_code == 200, r.text
        # verify gone from /jobs/mine
        r2 = requests.get(f"{API}/jobs/mine", headers=_h(emp_token))
        assert not any(j["id"] == jid for j in r2.json()), "job still present after delete"
        # and gone from public GET
        r3 = requests.get(f"{API}/jobs/{jid}")
        assert r3.status_code == 404
