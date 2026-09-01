"""Additional stress/regression tests for P0-004 atomic CPC debit.

These tests reuse the isolated fake Mongo semantics from test_cpc_concurrency.py
and exercise larger concurrent batches plus stale-read scenarios. No network,
real database, seed account, or secret is required.
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
BASE_TEST = HERE / "test_cpc_concurrency.py"

spec = importlib.util.spec_from_file_location("p0004_base_tests", BASE_TEST)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


@pytest.fixture
def jobs_module(monkeypatch):
    base._install_import_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("routes_jobs_p0004_stress", base.JOBS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def _no_low_balance(*args, **kwargs):
        return None

    module._check_low_balance = _no_low_balance
    module._HTTPException = base._HTTPException
    return module


def _run(module, db, count):
    async def scenario():
        async def _get_database():
            return db

        module.get_database = _get_database
        return await asyncio.gather(
            *(module.record_partner_click(base.JOB_ID) for _ in range(count))
        )

    return asyncio.run(scenario())


def _assert_batch(db, *, requests, cpc, expected_charged, initial_balance):
    profile = db.partner_profiles.profile
    expected_balance = initial_balance - (expected_charged * cpc)

    assert profile["balance"] == pytest.approx(expected_balance)
    assert profile["balance"] >= -1e-12
    assert profile["total_spent"] == pytest.approx(expected_charged * cpc)
    assert profile["total_clicks"] == requests
    assert len(db.click_events.records) == requests
    assert db.jobs.job["views_count"] == requests

    paid = [event for event in db.click_events.records if float(event["cost"]) > 0]
    free = [event for event in db.click_events.records if float(event["cost"]) == 0]
    assert len(paid) == expected_charged
    assert len(free) == requests - expected_charged
    assert all(float(event["cost"]) == pytest.approx(cpc) for event in paid)


@pytest.mark.parametrize(
    "balance,cpc,requests,expected_charged",
    [
        (0.0, 0.50, 20, 0),
        (0.49, 0.50, 20, 0),
        (0.50, 0.50, 20, 1),
        (1.00, 0.50, 20, 2),
        (2.50, 0.50, 50, 5),
        (1.00, 0.10, 50, 10),
        (0.35, 0.10, 50, 3),
    ],
)
def test_concurrency_matrix_never_overspends(jobs_module, balance, cpc, requests, expected_charged):
    db = base._FakeDB(balance=balance, cpc=cpc)
    responses = _run(jobs_module, db, requests)

    assert all(response == {"redirect_url": "https://example.test/job"} for response in responses)
    _assert_batch(
        db,
        requests=requests,
        cpc=cpc,
        expected_charged=expected_charged,
        initial_balance=balance,
    )

    assert len(db.partner_profiles.atomic_filters) == requests
    assert all(
        f == {"user_id": base.PARTNER_ID, "balance": {"$gte": cpc}}
        for f in db.partner_profiles.atomic_filters
    )


def test_large_batch_100_clicks_charges_only_available_balance(jobs_module):
    db = base._FakeDB(balance=5.0, cpc=0.5)
    _run(jobs_module, db, 100)

    _assert_batch(
        db,
        requests=100,
        cpc=0.5,
        expected_charged=10,
        initial_balance=5.0,
    )


def test_repeated_concurrent_batches_do_not_reopen_spend_window(jobs_module):
    db = base._FakeDB(balance=2.0, cpc=0.5)

    _run(jobs_module, db, 7)
    _run(jobs_module, db, 7)
    _run(jobs_module, db, 7)

    profile = db.partner_profiles.profile
    assert profile["balance"] == pytest.approx(0.0)
    assert profile["balance"] >= 0
    assert profile["total_spent"] == pytest.approx(2.0)
    assert profile["total_clicks"] == 21
    assert len(db.click_events.records) == 21
    assert sum(float(event["cost"]) > 0 for event in db.click_events.records) == 4
    assert sum(float(event["cost"]) == 0 for event in db.click_events.records) == 17
    assert db.jobs.job["views_count"] == 21


def test_stale_high_balance_read_cannot_force_extra_charge(jobs_module):
    db = base._FakeDB(balance=0.5, cpc=0.5)
    real_find_one = db.partner_profiles.find_one

    async def stale_find_one(query):
        doc = await real_find_one(query)
        if doc is not None:
            doc["balance"] = 999.0
        return doc

    db.partner_profiles.find_one = stale_find_one
    _run(jobs_module, db, 2)

    _assert_batch(
        db,
        requests=2,
        cpc=0.5,
        expected_charged=1,
        initial_balance=0.5,
    )


def test_stale_low_balance_read_does_not_block_valid_atomic_debits(jobs_module):
    db = base._FakeDB(balance=1.0, cpc=0.5)
    real_find_one = db.partner_profiles.find_one

    async def stale_find_one(query):
        doc = await real_find_one(query)
        if doc is not None:
            doc["balance"] = 0.0
        return doc

    db.partner_profiles.find_one = stale_find_one
    _run(jobs_module, db, 2)

    _assert_batch(
        db,
        requests=2,
        cpc=0.5,
        expected_charged=2,
        initial_balance=1.0,
    )


def test_non_per_click_mode_never_debits_but_still_counts_clicks(jobs_module):
    db = base._FakeDB(balance=10.0, cpc=0.5, billing_mode="per_impression")
    _run(jobs_module, db, 25)

    profile = db.partner_profiles.profile
    assert profile["balance"] == pytest.approx(10.0)
    assert profile["total_spent"] == pytest.approx(0.0)
    assert profile["total_clicks"] == 25
    assert len(db.click_events.records) == 25
    assert all(float(event["cost"]) == 0 for event in db.click_events.records)
    assert all(event["stopped"] is False for event in db.click_events.records)
    assert db.partner_profiles.atomic_filters == []


def test_negative_cpc_is_never_debited_or_stopped(jobs_module):
    db = base._FakeDB(balance=1.0, cpc=-0.5)
    _run(jobs_module, db, 10)

    profile = db.partner_profiles.profile
    assert profile["balance"] == pytest.approx(1.0)
    assert profile["total_spent"] == pytest.approx(0.0)
    assert profile["total_clicks"] == 10
    assert len(db.click_events.records) == 10
    assert all(float(event["cost"]) == 0 for event in db.click_events.records)
    assert all(event["stopped"] is False for event in db.click_events.records)
    assert db.jobs.job["is_active"] is True
    assert db.partner_profiles.atomic_filters == []


def test_default_cpc_is_atomic_under_concurrency(jobs_module):
    db = base._FakeDB(balance=0.75, cpc=None, default_cpc=0.25)
    _run(jobs_module, db, 10)

    _assert_batch(
        db,
        requests=10,
        cpc=0.25,
        expected_charged=3,
        initial_balance=0.75,
    )
