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
    """Exécute les clics en concurrence et collecte les issues ("ok"/"err").

    Depuis P0-006, un appel qui observe `is_active=False` (job arrêté pour
    solde CPC insuffisant) ou une campagne non diffusible retourne 404 — on le
    collecte au lieu de le laisser échouer la collecte. Les clics déjà admis
    avant l'arrêt se terminent normalement."""
    async def scenario():
        async def _get_database():
            return db

        module.get_database = _get_database

        async def _one():
            try:
                return ("ok", await module.record_partner_click(base.JOB_ID))
            except base._HTTPException as e:
                return ("err", e)

        return await asyncio.gather(*(_one() for _ in range(count)))

    results = asyncio.run(scenario())
    db.__results = results
    return results


def _split_results(db):
    """Sépare les issues collectées : liste de redirects et liste de 404."""
    results = getattr(db, "__results", [])
    redirects = [r for r in results if r[0] == "ok"]
    errors = [r for r in results if r[0] == "err"]
    assert all(e[1].status_code == 404 for e in errors), "seul un 404 est attendu"
    return redirects, errors


def _assert_batch(db, *, requests, cpc, expected_charged, initial_balance):
    """Invariants d'atomicité CPC sous le contrat P0-006 :
    - balance jamais négative, montant débité exact selon les crédits dispo ;
    - nombre de débits positifs exact, aucun double débit ;
    - chaque 404 ne produit ni débit ni event ni view supplémentaire ;
    - au moins un clic insuffisant arrête le job et est compté.
    """
    profile = db.partner_profiles.profile

    redirects, errors = _split_results(db)

    charged = sum(float(ev["cost"]) for ev in db.click_events.records if float(ev["cost"]) > 0)

    assert profile["balance"] >= -1e-12
    assert profile["balance"] == pytest.approx(initial_balance - charged)
    assert profile["total_spent"] == pytest.approx(expected_charged * cpc)

    # chaque redirect = 1 clic compté + 1 event + 1 view ; chaque 404 rien.
    assert profile["total_clicks"] == len(redirects)
    assert len(db.click_events.records) == len(redirects)
    assert db.jobs.job["views_count"] == len(redirects)

    paid = [ev for ev in db.click_events.records if float(ev["cost"]) > 0]
    free = [ev for ev in db.click_events.records if float(ev["cost"]) == 0]
    assert len(paid) == expected_charged
    assert len(free) == len(redirects) - expected_charged
    assert all(float(ev["cost"]) == pytest.approx(cpc) for ev in paid)
    # aucun double débit : montant exact au total
    assert sum(float(ev["cost"]) for ev in paid) == pytest.approx(expected_charged * cpc)

    # au moins un clic insuffisant a arrêté le job.
    if expected_charged < requests:
        assert db.jobs.job["is_active"] is False


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
    _run(jobs_module, db, requests)

    # chaque redirect est un succès ; les 404 (job arrêté) sont collectés.
    redirects, _ = _split_results(db)
    assert all(r[1] == {"redirect_url": "https://example.test/job"} for r in redirects)
    _assert_batch(
        db,
        requests=requests,
        cpc=cpc,
        expected_charged=expected_charged,
        initial_balance=balance,
    )

    # Chaque tentative de débit a bien filtré atomiquement `balance >= cpc`.
    redirects, errors = _split_results(db)
    assert len(db.partner_profiles.atomic_filters) == len(redirects)
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

    r1 = _run(jobs_module, db, 7)
    r2 = _run(jobs_module, db, 7)
    r3 = _run(jobs_module, db, 7)

    profile = db.partner_profiles.profile
    # Le premier batch a consommé exactement ce que permettait le solde (4 débits
    # pour 2.0/0.5), puis le job est arrêté. Les batchs suivants ne rouvrent
    # jamais la fenêtre de dépense : tout est 404, aucun débit/event/view.
    first_redirects = [r for r in r1 if r[0] == "ok"]
    assert len(first_redirects) >= 4
    assert all(r[0] == "err" for r in r2 + r3), "après arrêt, plus aucun clic admis"

    assert profile["balance"] == pytest.approx(0.0)
    assert profile["balance"] >= 0
    assert profile["total_spent"] == pytest.approx(2.0)
    assert profile["total_clicks"] == len(first_redirects)
    assert len(db.click_events.records) == len(first_redirects)
    assert sum(float(ev["cost"]) > 0 for ev in db.click_events.records) == 4
    assert sum(float(ev["cost"]) == 0 for ev in db.click_events.records) == len(first_redirects) - 4
    assert db.jobs.job["views_count"] == len(first_redirects)
    assert db.jobs.job["is_active"] is False


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
