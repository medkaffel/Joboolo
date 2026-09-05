"""Tests for LOT6 new features: AI recommendations/match, messaging, recruiter analytics."""
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)

# E2E credentials must come from environment — no repository fallbacks
CAND_EMAIL = os.environ.get("E2E_CANDIDATE_EMAIL", "candidate@test.fr")
CAND_PWD = os.environ.get("E2E_CANDIDATE_PASSWORD")
EMP_EMAIL = os.environ.get("E2E_EMPLOYER_EMAIL", "recruteur@techcorp.fr")
EMP_PWD = os.environ.get("E2E_EMPLOYER_PASSWORD")

CAND = {"email": CAND_EMAIL, "password": CAND_PWD}
EMP = {"email": EMP_EMAIL, "password": EMP_PWD}

AI_TIMEOUT = 120


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"Login failed for {creds['email']}: {r.status_code} {r.text[:300]}")
    data = r.json()
    tok = data.get("token")
    token = tok.get("access_token") if isinstance(tok, dict) else (tok or data.get("access_token"))
    assert token, f"No token in login response: {data}"
    return token, data.get("user", {})


@pytest.fixture(scope="session")
def cand_auth():
    if not CAND_PWD:
        pytest.skip("E2E_CANDIDATE_PASSWORD not set")
    token, user = _login(CAND)
    return {"headers": {"Authorization": f"Bearer {token}"}, "user": user}


@pytest.fixture(scope="session")
def emp_auth():
    if not EMP_PWD:
        pytest.skip("E2E_EMPLOYER_PASSWORD not set")
    token, user = _login(EMP)
    return {"headers": {"Authorization": f"Bearer {token}"}, "user": user}


@pytest.fixture(scope="session")
def stranger_auth():
    """Fresh unrelated candidate for negative messaging test."""
    email = f"TEST_stranger_{uuid.uuid4().hex[:8]}@test.fr"
    # Use a generated per-run password for this temporary test account
    pwd = f"StrangerTest_{uuid.uuid4().hex[:8]}"
    payload = {
        "email": email, "password": pwd, "first_name": "TEST",
        "last_name": "Stranger", "user_type": "candidate",
    }
    r = requests.post(f"{BASE_URL}/api/auth/register", json=payload, timeout=30)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text[:300]}"
    d = r.json()
    tok = d.get("token")
    token = tok.get("access_token") if isinstance(tok, dict) else (tok or d.get("access_token"))
    assert token
    return {"headers": {"Authorization": f"Bearer {token}"}, "user": d.get("user", {}), "email": email}


# ---------------- Auth / smoke ----------------
class TestAuthSmoke:
    def test_candidate_login(self, cand_auth):
        assert cand_auth["user"].get("user_type") == "candidate"

    def test_employer_login(self, emp_auth):
        assert emp_auth["user"].get("user_type") == "employer"


# ---------------- AI recommendations ----------------
class TestAIRecommendations:
    def test_recommendations_candidate(self, cand_auth):
        r = requests.get(f"{BASE_URL}/api/ai/recommendations", headers=cand_auth["headers"], timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert set(["profile_complete", "recommendations", "ai"]).issubset(d.keys())
        assert isinstance(d["recommendations"], list)
        assert d["profile_complete"] is True
        assert len(d["recommendations"]) > 0, "No recommendations returned"
        first = d["recommendations"][0]
        assert "job" in first and first["job"].get("id")
        assert "_id" not in first["job"]

    def test_recommendations_are_ai_scored_and_relevant(self, cand_auth):
        """Seed candidate skills = JavaScript/React/Node.js/Python -> recs should be AI-scored & tech."""
        r = requests.get(f"{BASE_URL}/api/ai/recommendations", headers=cand_auth["headers"], timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        recs = d["recommendations"]
        assert d["ai"] is True, (
            "AI ranking produced no result (ai=False) -> recommendations returned without "
            f"score/reason. Titles: {[x['job'].get('title') for x in recs][:5]}"
        )
        first = recs[0]
        assert isinstance(first["score"], int) and 0 <= first["score"] <= 100
        assert first["reason"], "Missing AI reason"
        skills = ["javascript", "react", "node", "python", "développeur", "developpeur", "dev"]
        titles = " ".join((x["job"].get("title") or "") for x in recs).lower()
        assert any(s in titles for s in skills), f"No skill-relevant job recommended. Titles: {titles[:300]}"

    def test_recommendations_forbidden_for_employer(self, emp_auth):
        r = requests.get(f"{BASE_URL}/api/ai/recommendations", headers=emp_auth["headers"], timeout=60)
        assert r.status_code == 403, r.text[:300]

    def test_recommendations_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/ai/recommendations", timeout=30)
        assert r.status_code in (401, 403)


# ---------------- AI match (candidate -> job) ----------------
class TestAIMatchJob:
    def test_match_job(self, cand_auth):
        jobs = requests.get(f"{BASE_URL}/api/jobs?limit=1", timeout=30)
        assert jobs.status_code == 200
        payload = jobs.json()
        items = payload.get("jobs") if isinstance(payload, dict) else payload
        assert items, "No jobs available"
        job_id = items[0]["id"]

        r = requests.post(f"{BASE_URL}/api/ai/match/{job_id}", headers=cand_auth["headers"], timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert isinstance(d["score"], int) and 0 <= d["score"] <= 100
        assert d["verdict"] and d["summary"]
        assert isinstance(d["strengths"], list) and isinstance(d["gaps"], list)
        assert d["summary"] != "Analyse indisponible pour le moment.", "LLM returned no usable summary"

    def test_match_job_404(self, cand_auth):
        r = requests.post(f"{BASE_URL}/api/ai/match/does-not-exist", headers=cand_auth["headers"], timeout=60)
        assert r.status_code == 404

    def test_match_job_forbidden_for_employer(self, emp_auth):
        r = requests.post(f"{BASE_URL}/api/ai/match/job_1", headers=emp_auth["headers"], timeout=60)
        assert r.status_code == 403


# ---------------- AI match (employer -> application) ----------------
class TestAIMatchApplication:
    def test_match_application(self, emp_auth):
        jr = requests.get(f"{BASE_URL}/api/jobs/mine", headers=emp_auth["headers"], timeout=30)
        assert jr.status_code == 200, jr.text[:300]
        payload = jr.json()
        my_jobs = payload.get("jobs") if isinstance(payload, dict) else payload
        assert my_jobs, "Employer has no jobs"

        app_id = None
        for j in my_jobs:
            ar = requests.get(f"{BASE_URL}/api/applications/job/{j['id']}", headers=emp_auth["headers"], timeout=30)
            if ar.status_code == 200:
                apps = ar.json()
                apps = apps.get("applications") if isinstance(apps, dict) else apps
                if apps:
                    app_id = apps[0]["id"]
                    assert apps[0].get("job", {}).get("employer_id"), "job.employer_id missing in application response"
                    break
        assert app_id, "No applications found for employer jobs"

        r = requests.get(f"{BASE_URL}/api/ai/match/application/{app_id}", headers=emp_auth["headers"], timeout=AI_TIMEOUT)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert 0 <= d["score"] <= 100
        assert d["verdict"] and d["summary"]

    def test_match_application_forbidden_for_candidate(self, cand_auth):
        r = requests.get(f"{BASE_URL}/api/ai/match/application/whatever", headers=cand_auth["headers"], timeout=60)
        assert r.status_code == 403

    def test_match_application_404(self, emp_auth):
        r = requests.get(f"{BASE_URL}/api/ai/match/application/nope-{uuid.uuid4().hex}", headers=emp_auth["headers"], timeout=60)
        assert r.status_code == 404


# ---------------- Messaging ----------------
class TestMessaging:
    def test_can_contact_allowed(self, cand_auth, emp_auth):
        emp_id = emp_auth["user"]["id"]
        r = requests.get(f"{BASE_URL}/api/messages/can-contact/{emp_id}", headers=cand_auth["headers"], timeout=30)
        assert r.status_code == 200
        assert r.json()["allowed"] is True

    def test_candidate_sends_and_employer_reads(self, cand_auth, emp_auth):
        emp_id = emp_auth["user"]["id"]
        cand_id = cand_auth["user"]["id"]
        text = f"TEST_msg_{uuid.uuid4().hex[:6]}"

        # clear any pre-existing unread in this thread so the baseline is deterministic
        requests.get(f"{BASE_URL}/api/messages/thread/{cand_id}", headers=emp_auth["headers"], timeout=30)
        u0 = requests.get(f"{BASE_URL}/api/messages/unread-count", headers=emp_auth["headers"], timeout=30)
        assert u0.status_code == 200
        before = u0.json()["count"]

        s = requests.post(f"{BASE_URL}/api/messages", headers=cand_auth["headers"],
                          json={"recipient_id": emp_id, "text": text}, timeout=30)
        assert s.status_code == 200, s.text[:300]
        sent = s.json()
        assert sent["text"] == text and sent["from_me"] is True and sent["id"]

        # employer unread incremented
        time.sleep(0.5)
        u1 = requests.get(f"{BASE_URL}/api/messages/unread-count", headers=emp_auth["headers"], timeout=30)
        assert u1.json()["count"] == before + 1

        # employer conversation list shows unread
        c = requests.get(f"{BASE_URL}/api/messages/conversations", headers=emp_auth["headers"], timeout=30)
        assert c.status_code == 200
        convos = c.json()
        mine = [x for x in convos if x["other_id"] == cand_id]
        assert mine, "Candidate conversation missing for employer"
        assert mine[0]["unread"] >= 1
        assert mine[0]["last_message"] == text
        assert mine[0]["last_from_me"] is False
        assert mine[0]["name"] and mine[0]["name"] != "Utilisateur"

        # employer opens thread -> marks read
        t = requests.get(f"{BASE_URL}/api/messages/thread/{cand_id}", headers=emp_auth["headers"], timeout=30)
        assert t.status_code == 200
        td = t.json()
        assert td["other"]["id"] == cand_id
        assert any(m["text"] == text and m["from_me"] is False for m in td["messages"])

        u2 = requests.get(f"{BASE_URL}/api/messages/unread-count", headers=emp_auth["headers"], timeout=30)
        assert u2.json()["count"] == before, "Thread open did not mark messages read"

        # employer replies
        reply = f"TEST_reply_{uuid.uuid4().hex[:6]}"
        r2 = requests.post(f"{BASE_URL}/api/messages", headers=emp_auth["headers"],
                           json={"recipient_id": cand_id, "text": reply}, timeout=30)
        assert r2.status_code == 200, r2.text[:300]
        t2 = requests.get(f"{BASE_URL}/api/messages/thread/{emp_id}", headers=cand_auth["headers"], timeout=30)
        assert t2.status_code == 200
        assert any(m["text"] == reply and m["from_me"] is False for m in t2.json()["messages"])

    def test_empty_message_rejected(self, cand_auth, emp_auth):
        r = requests.post(f"{BASE_URL}/api/messages", headers=cand_auth["headers"],
                          json={"recipient_id": emp_auth["user"]["id"], "text": "   "}, timeout=30)
        assert r.status_code == 400

    def test_unrelated_user_forbidden(self, stranger_auth, emp_auth):
        r = requests.post(f"{BASE_URL}/api/messages", headers=stranger_auth["headers"],
                          json={"recipient_id": emp_auth["user"]["id"], "text": "TEST_hello"}, timeout=30)
        assert r.status_code == 403, r.text[:300]

    def test_self_message_forbidden(self, cand_auth):
        r = requests.post(f"{BASE_URL}/api/messages", headers=cand_auth["headers"],
                          json={"recipient_id": cand_auth["user"]["id"], "text": "TEST_self"}, timeout=30)
        assert r.status_code == 403

    def test_nonexistent_recipient(self, cand_auth):
        r = requests.post(f"{BASE_URL}/api/messages", headers=cand_auth["headers"],
                          json={"recipient_id": "nope-" + uuid.uuid4().hex, "text": "TEST"}, timeout=30)
        assert r.status_code == 403

    def test_messages_require_auth(self):
        r = requests.get(f"{BASE_URL}/api/messages/conversations", timeout=30)
        assert r.status_code in (401, 403)


# ---------------- Recruiter analytics ----------------
class TestRecruiterAnalytics:
    def test_analytics(self, emp_auth):
        r = requests.get(f"{BASE_URL}/api/analytics/recruiter", headers=emp_auth["headers"], timeout=60)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        for k in ("totals", "status_totals", "per_job", "timeline"):
            assert k in d
        t = d["totals"]
        assert t["jobs"] >= 1
        assert t["active_jobs"] <= t["jobs"]
        assert t["views"] >= 0 and t["applications"] >= 0
        assert len(d["timeline"]) == 14
        assert sum(x["count"] for x in d["timeline"]) <= t["applications"]
        assert sum(d["status_totals"].values()) == t["applications"]
        assert len(d["per_job"]) == t["jobs"]
        pj = d["per_job"][0]
        for k in ("id", "title", "views", "applications", "status_counts", "conversion", "created_at"):
            assert k in pj
        # sorted desc by applications
        counts = [x["applications"] for x in d["per_job"]]
        assert counts == sorted(counts, reverse=True)

    def test_analytics_forbidden_for_candidate(self, cand_auth):
        r = requests.get(f"{BASE_URL}/api/analytics/recruiter", headers=cand_auth["headers"], timeout=30)
        assert r.status_code == 403

    def test_analytics_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/analytics/recruiter", timeout=30)
        assert r.status_code in (401, 403)
