"""P0-005 — Recruiter entitlements enforcement tests.

Covers:
- Zero credits → job creation rejected (402)
- Exactly one credit → consumed, balance decremented to 0
- Concurrent requests with one credit → only one succeeds
- Multiple credits → successive creations succeed
- Non-premium actions do not consume credits
- Credit never goes negative
- Payment idempotency (double webhook/status does not double-credit)
- Crash recovery (grant before credited flag → no double grant on retry)
"""
import os
import time
import threading
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except FileNotFoundError:
        pass

API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
DB_NAME = os.environ.get("DB_NAME", "indeed_clone")

EMPLOYER = ("recruteur@techcorp.fr", "password123", "employer")


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
    yield client[DB_NAME]
    client.close()


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
    return _login(client, EMPLOYER)


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _set_premium_credits(mongo_db, email, credits):
    """Directly set premium_credits on a user via pymongo."""
    mongo_db.users.update_one(
        {"email": email},
        {"$set": {"premium_credits": credits}},
    )


def _get_premium_credits(mongo_db, email):
    """Read premium_credits from a user."""
    user = mongo_db.users.find_one({"email": email})
    return (user or {}).get("premium_credits", 0)


def _ensure_company(client, employer_token, mongo_db):
    """Ensure the employer has at least one company. Returns company_id."""
    r = requests.get(f"{API}/companies/mine", headers=_h(employer_token))
    if r.status_code == 200:
        companies = r.json()
        if companies:
            return companies[0].get("id") or companies[0].get("_id")
    name = f"TEST_P0005_Co_{int(time.time())}"
    r = requests.post(f"{API}/companies/", headers=_h(employer_token), json={
        "name": name, "description": "P0-005 test", "location": "Paris",
        "industry": "Tech", "size": "1-10",
    })
    assert r.status_code == 200, f"Company creation failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    return data.get("id") or data.get("_id")


def _create_job_payload(company_id, suffix=""):
    return {
        "title": f"TEST P0-005 Dev{suffix}",
        "description": "P0-005 test job description for enforcement testing",
        "company_id": company_id,
        "location": "Paris",
        "job_type": "CDI",
        "salary_min": 40000,
        "salary_max": 60000,
    }


# ---------------------------------------------------------------------------
# Test: Zero credits → 402
# ---------------------------------------------------------------------------
class TestZeroCredits:
    def test_zero_credits_rejects_job_creation(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 0)
        company_id = _ensure_company(client, employer_token, mongo_db)
        r = requests.post(
            f"{API}/jobs",
            headers=_h(employer_token),
            json=_create_job_payload(company_id, "_zero"),
        )
        assert r.status_code == 402, f"Expected 402, got {r.status_code}: {r.text[:300]}"
        assert _get_premium_credits(mongo_db, EMPLOYER[0]) == 0


# ---------------------------------------------------------------------------
# Test: Exactly one credit → consumed, balance to 0
# ---------------------------------------------------------------------------
class TestSingleCredit:
    def test_single_credit_consumed_exactly(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 1)
        company_id = _ensure_company(client, employer_token, mongo_db)
        r = requests.post(
            f"{API}/jobs",
            headers=_h(employer_token),
            json=_create_job_payload(company_id, "_single"),
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"
        assert _get_premium_credits(mongo_db, EMPLOYER[0]) == 0


# ---------------------------------------------------------------------------
# Test: Concurrent requests with one credit → only one succeeds
# ---------------------------------------------------------------------------
class TestConcurrentSingleCredit:
    def test_concurrent_single_credit(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 1)
        company_id = _ensure_company(client, employer_token, mongo_db)
        headers = _h(employer_token)

        results = [None, None]

        def _try_create(idx):
            try:
                r = requests.post(
                    f"{API}/jobs",
                    headers=headers,
                    json=_create_job_payload(company_id, f"_conc_{idx}"),
                )
                results[idx] = r.status_code
            except Exception as e:
                results[idx] = f"error: {e}"

        t1 = threading.Thread(target=_try_create, args=(0,))
        t2 = threading.Thread(target=_try_create, args=(1,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one should succeed (200), the other should fail (402)
        assert sorted(results) == [200, 402], f"Expected [200, 402], got {results}"
        assert _get_premium_credits(mongo_db, EMPLOYER[0]) == 0


# ---------------------------------------------------------------------------
# Test: Multiple credits → successive creations succeed
# ---------------------------------------------------------------------------
class TestMultipleCredits:
    def test_multiple_credits_decrement(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 3)
        company_id = _ensure_company(client, employer_token, mongo_db)
        for i in range(3):
            r = requests.post(
                f"{API}/jobs",
                headers=_h(employer_token),
                json=_create_job_payload(company_id, f"_multi_{i}"),
            )
            assert r.status_code == 200, f"Attempt {i}: expected 200, got {r.status_code}"
        assert _get_premium_credits(mongo_db, EMPLOYER[0]) == 0
        # 4th attempt should fail
        r = requests.post(
            f"{API}/jobs",
            headers=_h(employer_token),
            json=_create_job_payload(company_id, "_multi_extra"),
        )
        assert r.status_code == 402, f"Expected 402 on exhausted credits, got {r.status_code}"


# ---------------------------------------------------------------------------
# Test: Non-premium actions do not consume credits
# ---------------------------------------------------------------------------
class TestNonPremiumFree:
    def test_search_does_not_consume_credits(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 5)
        r = requests.get(f"{API}/jobs", params={"search": "test"})
        assert r.status_code == 200
        assert _get_premium_credits(mongo_db, EMPLOYER[0]) == 5

    def test_my_jobs_does_not_consume_credits(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 5)
        r = requests.get(f"{API}/jobs/mine", headers=_h(employer_token))
        assert r.status_code == 200
        assert _get_premium_credits(mongo_db, EMPLOYER[0]) == 5

    def test_suggest_does_not_consume_credits(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 5)
        r = requests.get(f"{API}/jobs/suggest", params={"q": "dev"})
        assert r.status_code == 200
        assert _get_premium_credits(mongo_db, EMPLOYER[0]) == 5


# ---------------------------------------------------------------------------
# Test: Credit never goes negative
# ---------------------------------------------------------------------------
class TestCreditNeverNegative:
    def test_negative_credit_impossible(self, client, employer_token, mongo_db):
        _set_premium_credits(mongo_db, EMPLOYER[0], 0)
        company_id = _ensure_company(client, employer_token, mongo_db)
        r = requests.post(
            f"{API}/jobs",
            headers=_h(employer_token),
            json=_create_job_payload(company_id, "_neg"),
        )
        assert r.status_code == 402
        credits = _get_premium_credits(mongo_db, EMPLOYER[0])
        assert credits >= 0, f"Credits went negative: {credits}"


# ---------------------------------------------------------------------------
# Test: Payment idempotency — double webhook does not double-credit
# ---------------------------------------------------------------------------
class TestPaymentIdempotency:
    def test_double_webhook_no_double_credit(self, mongo_db):
        """Simulate: insert a paid transaction, then call _credit_if_paid twice.
        Verify the user receives credits only once."""
        from datetime import datetime, timezone

        session_id = f"cs_test_idempotent_{int(time.time())}"
        user_id = "test_user_idempotent"
        postings = 3

        # Create the user with 0 credits
        mongo_db.users.update_one(
            {"_id": user_id},
            {"$set": {
                "email": "test_idempotent@example.com",
                "premium_credits": 0,
                "first_name": "Test", "last_name": "Idempotent",
                "user_type": "employer", "is_active": True,
            }},
            upsert=True,
        )

        # Insert a paid transaction
        now = datetime.now(timezone.utc)
        mongo_db.payment_transactions.insert_one({
            "session_id": session_id,
            "user_id": user_id,
            "amount": 299.0,
            "currency": "eur",
            "kind": "recruiter_pack",
            "pack_id": "premium_1",
            "postings": postings,
            "status": "completed",
            "payment_status": "paid",
            "credited": False,
            "initiated_by": user_id,
            "created_at": now,
            "updated_at": now,
        })

        # Import and call _credit_if_paid twice
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from routes.payments import _credit_if_paid

        # First call — should grant credits
        import asyncio
        asyncio.get_event_loop().run_until_complete(_credit_if_paid(mongo_db, session_id))
        user = mongo_db.users.find_one({"_id": user_id})
        assert user["premium_credits"] == postings, (
            f"First credit failed: expected {postings}, got {user['premium_credits']}"
        )

        # Second call — should NOT double-credit
        asyncio.get_event_loop().run_until_complete(_credit_if_paid(mongo_db, session_id))
        user = mongo_db.users.find_one({"_id": user_id})
        assert user["premium_credits"] == postings, (
            f"Double credit: expected {postings}, got {user['premium_credits']}"
        )

        # Verify transaction is marked credited
        txn = mongo_db.payment_transactions.find_one({"session_id": session_id})
        assert txn["credited"] is True

        # Cleanup
        mongo_db.users.delete_one({"_id": user_id})
        mongo_db.payment_transactions.delete_one(
            {"session_id": session_id}
        )


# ---------------------------------------------------------------------------
# Test: Crash recovery — grant before credited flag → no double grant on retry
# ---------------------------------------------------------------------------
class TestCrashRecovery:
    def test_grant_before_credited_no_double_on_retry(self, mongo_db):
        """Simulate crash: grant credits, but do NOT set credited=True.
        On retry, the $addToSet guard prevents double-credit."""
        from datetime import datetime, timezone

        session_id = f"cs_test_crash_{int(time.time())}"
        user_id = "test_user_crash"
        postings = 2

        mongo_db.users.update_one(
            {"_id": user_id},
            {"$set": {
                "email": "test_crash@example.com",
                "premium_credits": 0,
                "first_name": "Test", "last_name": "Crash",
                "user_type": "employer", "is_active": True,
            }},
            upsert=True,
        )

        now = datetime.now(timezone.utc)
        mongo_db.payment_transactions.insert_one({
            "session_id": session_id,
            "user_id": user_id,
            "amount": 598.0,
            "currency": "eur",
            "kind": "recruiter_pack",
            "pack_id": "premium_3",
            "postings": postings,
            "status": "completed",
            "payment_status": "paid",
            "credited": False,
            "initiated_by": user_id,
            "created_at": now,
            "updated_at": now,
        })

        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from routes.payments import _credit_if_paid
        import asyncio

        # First call — grants credits and sets credited=True
        asyncio.get_event_loop().run_until_complete(_credit_if_paid(mongo_db, session_id))
        user = mongo_db.users.find_one({"_id": user_id})
        assert user["premium_credits"] == postings

        # Simulate crash: reset credited to False (but keep granted_sessions)
        mongo_db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {"credited": False}},
        )

        # Retry — should NOT double-credit because granted_sessions contains session_id
        asyncio.get_event_loop().run_until_complete(_credit_if_paid(mongo_db, session_id))
        user = mongo_db.users.find_one({"_id": user_id})
        assert user["premium_credits"] == postings, (
            f"Double credit after crash: expected {postings}, got {user['premium_credits']}"
        )

        # Cleanup
        mongo_db.users.delete_one({"_id": user_id})
        mongo_db.payment_transactions.delete_one(
            {"session_id": session_id}
        )


# ---------------------------------------------------------------------------
# Test: Missing premium_credits field treated as 0
# ---------------------------------------------------------------------------
class TestMissingCreditsField:
    def test_missing_premium_credits_field_treated_as_zero(self, client, employer_token, mongo_db):
        # Remove premium_credits field entirely
        mongo_db.users.update_one(
            {"email": EMPLOYER[0]},
            {"$unset": {"premium_credits": ""}},
        )
        company_id = _ensure_company(client, employer_token, mongo_db)
        r = requests.post(
            f"{API}/jobs",
            headers=_h(employer_token),
            json=_create_job_payload(company_id, "_missing_field"),
        )
        assert r.status_code == 402, f"Expected 402, got {r.status_code}"
