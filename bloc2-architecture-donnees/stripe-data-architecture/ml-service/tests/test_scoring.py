"""
Tests unitaires du ML service (pytest).

Lancement :
    cd ml-service
    pip install -r requirements-dev.txt
    PYTHONPATH=. pytest tests/ -v
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Env minimal attendu par main.py (MONGO_URI fail-fast)."""
    monkeypatch.setenv("MONGO_URI", "mongodb://fake:fake@localhost:27017")
    monkeypatch.setenv("ML_DEV_ALLOW_NO_AUTH", "1")
    monkeypatch.setenv("ML_API_KEYS", "")
    # Force un reimport propre entre tests
    if "app.main" in sys.modules:
        importlib.reload(sys.modules["app.main"])


def _import_main():
    from app import main as m
    return m


# ---------------------------------------------------------------------------
# score_rulebased — scénarios heuristiques
# ---------------------------------------------------------------------------

def test_score_rulebased_baseline_low():
    m = _import_main()
    req = m.ScoreRequest(
        transaction_id="t1", customer_id="c1", merchant_id="m1",
        amount_usd=20, currency_code="USD", device_type="mobile", ip_country="FR",
    )
    score, reasons = m.score_rulebased({}, req)
    assert 0.0 <= score <= 0.3
    assert reasons == [] or reasons == []  # baseline = aucune raison spécifique


def test_score_rulebased_high_amount_flagged():
    m = _import_main()
    req = m.ScoreRequest(
        transaction_id="t2", customer_id="c2", merchant_id="m2",
        amount_usd=6000, currency_code="USD", ip_country="FR",
    )
    score, reasons = m.score_rulebased({}, req)
    assert "high_amount" in reasons
    assert "very_high_amount" in reasons
    assert score > 0.3


def test_score_rulebased_high_risk_country():
    m = _import_main()
    req = m.ScoreRequest(
        transaction_id="t3", customer_id="c3", merchant_id="m3",
        amount_usd=50, currency_code="USD", ip_country="NG",
    )
    _, reasons = m.score_rulebased({}, req)
    assert "high_risk_country" in reasons


def test_score_rulebased_velocity_anomaly():
    m = _import_main()
    req = m.ScoreRequest(
        transaction_id="t4", customer_id="c4", merchant_id="m4",
        amount_usd=100, currency_code="EUR", ip_country="FR",
    )
    features = {"tx_count_24h": 15, "velocity_score": 0.85, "risk_score": 0.6}
    score, reasons = m.score_rulebased(features, req)
    assert "high_velocity_24h" in reasons
    assert "velocity_anomaly" in reasons
    assert "high_customer_risk" in reasons
    assert score >= 0.7


# ---------------------------------------------------------------------------
# decide — seuils
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (0.0, "approve"),
    (0.29, "approve"),
    (0.3, "review"),
    (0.5, "review"),
    (0.69, "review"),
    (0.7, "block"),
    (1.0, "block"),
])
def test_decide_thresholds(score, expected):
    m = _import_main()
    assert m.decide(score) == expected


# ---------------------------------------------------------------------------
# fetch_features — fallback si absent
# ---------------------------------------------------------------------------

class _FakeCollection:
    def __init__(self, doc=None):
        self._doc = doc
    def find_one(self, _q):
        return self._doc

class _FakeDB:
    def __init__(self, doc=None):
        self.ml_features_customer = _FakeCollection(doc)


def test_fetch_features_missing_returns_defaults():
    m = _import_main()
    feats = m.fetch_features(_FakeDB(doc=None), "unknown_customer")
    assert feats == {
        "tx_count_24h": 0,
        "tx_amount_sum_24h": 0.0,
        "velocity_score": 0.0,
        "risk_score": 0.0,
    }


def test_fetch_features_present_returns_features():
    m = _import_main()
    stored = {"features": {"tx_count_24h": 7, "velocity_score": 0.4}}
    feats = m.fetch_features(_FakeDB(doc=stored), "c1")
    assert feats == {"tx_count_24h": 7, "velocity_score": 0.4}


# ---------------------------------------------------------------------------
# /health endpoint via TestClient
# ---------------------------------------------------------------------------

def test_health_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    m = _import_main()

    # Mock MongoClient pour que lifespan n'échoue pas
    class _FakeMongo:
        def get_database(self, _n): return _FakeDB(doc=None)
        def close(self): pass

    monkeypatch.setattr(m, "MongoClient", lambda *a, **k: _FakeMongo())

    with TestClient(m.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "model_version" in body
        assert body["engine"] in ("xgboost", "rule-based")
