"""
Stripe ML Service — Fraud scoring temps réel.

FIX v3-hauts :
- Docstring honnête (retrait des mentions XGBoost/Kafka fantômes en v2).
- Ajout d'une authentification par API key (header X-API-Key).
- Ajout d'un rate limit 120 req/min via slowapi.
- Logging structuré JSON (python-json-logger) au lieu de print().
- Chargement dynamique d'un modèle XGBoost picklé si ML_MODEL_PATH existe,
  sinon fallback sur la logique rule-based (score_rulebased).
- Fail-fast si MONGO_URI manque (plus de fallback hardcodé en clair).

Endpoints :
  POST /score       → score a transaction (auth requise)
  GET  /health      → liveness probe (publique)
  GET  /metrics     → Prometheus metrics (publique, scrape interne)

DAMA-DMBOK2 ch.14 §2.2 — Big Data & Data Science
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import random
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pymongo import MongoClient
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_429_TOO_MANY_REQUESTS

# -----------------------------------------------------------------------------
# Logging structuré JSON
# -----------------------------------------------------------------------------
class JSONFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)

_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(JSONFormatter())
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), handlers=[_h])
logger = logging.getLogger("stripe.ml")

# -----------------------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "fraud_score_requests_total", "Total fraud scoring requests", ["decision"]
)
REQUEST_LATENCY = Histogram(
    "fraud_score_latency_seconds", "Latency of fraud scoring",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)
AUTH_FAIL = Counter("fraud_score_auth_failures_total", "API key auth failures")

# -----------------------------------------------------------------------------
# Pydantic models
# -----------------------------------------------------------------------------
class ScoreRequest(BaseModel):
    transaction_id: str
    customer_id: str
    merchant_id: str
    amount_usd: float = Field(..., gt=0)
    currency_code: str
    device_type: Optional[str] = None
    ip_country: Optional[str] = None


class ScoreResponse(BaseModel):
    transaction_id: str
    score: float
    decision: str
    model_version: str
    reasons: list[str]
    scored_at: datetime


# -----------------------------------------------------------------------------
# Rate limiter (par IP source)
# -----------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


# -----------------------------------------------------------------------------
# API key auth
# -----------------------------------------------------------------------------
API_KEYS = {k.strip() for k in os.environ.get("ML_API_KEYS", "").split(",") if k.strip()}

async def require_api_key(request: Request):
    # FIX v3-hauts: si aucune clé configurée, on autorise seulement en DEV
    # explicite (ML_DEV_ALLOW_NO_AUTH=1). En prod ML_API_KEYS doit être set.
    if not API_KEYS:
        if os.environ.get("ML_DEV_ALLOW_NO_AUTH") == "1":
            return
        AUTH_FAIL.inc()
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="API keys not configured (set ML_API_KEYS or ML_DEV_ALLOW_NO_AUTH=1)",
        )
    key = request.headers.get("x-api-key")
    if key not in API_KEYS:
        AUTH_FAIL.inc()
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )


# -----------------------------------------------------------------------------
# Model loading (XGBoost si dispo, sinon règles)
# -----------------------------------------------------------------------------
MODEL_VERSION = os.environ.get("ML_MODEL_VERSION", "v2026.04.19")
_MODEL_BUNDLE = None

def _try_load_xgb_model():
    global _MODEL_BUNDLE
    path = os.environ.get("ML_MODEL_PATH", "")
    if not path or not os.path.exists(path):
        logger.info("No XGBoost model found at %s — using rule-based fallback", path or "<unset>")
        return
    try:
        with open(path, "rb") as f:
            _MODEL_BUNDLE = pickle.load(f)
        logger.info("Loaded XGBoost model from %s (features=%d)",
                    path, len(_MODEL_BUNDLE.get("feature_order", [])))
    except Exception as exc:
        logger.exception("Failed to load model at %s: %s — fallback to rule-based", path, exc)
        _MODEL_BUNDLE = None


# -----------------------------------------------------------------------------
# Lifespan — init MongoDB connection + load model
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # FIX v3-hauts: fail-fast si MONGO_URI manque (pas de fallback password clair)
    uri = os.environ.get("MONGO_URI")
    if not uri:
        logger.error("MONGO_URI is not set — aborting")
        raise RuntimeError("MONGO_URI env var is required")

    app.state.mongo = MongoClient(uri, serverSelectionTimeoutMS=5000)
    app.state.db = app.state.mongo.get_database("stripe_nosql")
    _try_load_xgb_model()
    logger.info("ML service started — mongo=ok, model=%s",
                "xgboost" if _MODEL_BUNDLE else "rule-based")
    yield
    app.state.mongo.close()
    logger.info("ML service stopped")


app = FastAPI(
    title="Stripe Fraud Scoring API",
    version=MODEL_VERSION,
    lifespan=lifespan,
)

# Brancher le rate limiter sur FastAPI
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return Response(
        content=json.dumps({"detail": "rate limit exceeded"}),
        status_code=HTTP_429_TOO_MANY_REQUESTS,
        media_type="application/json",
    )


# -----------------------------------------------------------------------------
# Feature lookup
# -----------------------------------------------------------------------------
def fetch_features(db, customer_id: str) -> dict:
    """Lookup customer features from MongoDB feature store (online)."""
    doc = db.ml_features_customer.find_one({"customer_id": customer_id})
    if not doc:
        return {
            "tx_count_24h": 0,
            "tx_amount_sum_24h": 0.0,
            "velocity_score": 0.0,
            "risk_score": 0.0,
        }
    return doc.get("features", {})


# -----------------------------------------------------------------------------
# Scoring strategies
# -----------------------------------------------------------------------------
def score_rulebased(features: dict, request: ScoreRequest) -> tuple[float, list[str]]:
    """Règles heuristiques — fallback utilisé quand aucun modèle XGBoost n'est chargé."""
    reasons: list[str] = []
    score = 0.1

    amount = request.amount_usd
    tx24 = features.get("tx_count_24h", 0)
    velocity = features.get("velocity_score", 0.0)
    customer_risk = features.get("risk_score", 0.0)

    if amount > 1000:
        score += 0.15; reasons.append("high_amount")
    if amount > 5000:
        score += 0.20; reasons.append("very_high_amount")
    if tx24 > 10:
        score += 0.25; reasons.append("high_velocity_24h")
    if velocity > 0.7:
        score += 0.15; reasons.append("velocity_anomaly")
    if customer_risk > 0.5:
        score += 0.20; reasons.append("high_customer_risk")
    if request.ip_country and request.ip_country in {"NG", "RU"}:
        score += 0.15; reasons.append("high_risk_country")

    score = min(1.0, max(0.0, score + random.uniform(-0.02, 0.02)))
    return score, reasons


def score_xgboost(bundle: dict, features: dict, request: ScoreRequest) -> tuple[float, list[str]]:
    """Inference via modèle XGBoost picklé par le DAG ml_fraud_scoring."""
    import numpy as np
    model = bundle["model"]
    feature_order = bundle["feature_order"]

    base = {
        "amount_usd": request.amount_usd,
        "is_3d_secure": 0,
        "country_is_high_risk": 1 if (request.ip_country in {"NG", "RU"}) else 0,
    }
    # Ajoute les features de feature store + features one-hot manquantes à 0
    for k in feature_order:
        if k not in base:
            base[k] = features.get(k, 0)

    X = np.array([[base.get(col, 0) for col in feature_order]], dtype=float)
    proba = float(model.predict_proba(X)[0, 1])
    reasons = ["xgboost_proba"]
    if request.ip_country in {"NG", "RU"}:
        reasons.append("high_risk_country")
    return proba, reasons


def decide(score: float) -> str:
    if score < 0.3:
        return "approve"
    if score < 0.7:
        return "review"
    return "block"


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_version": MODEL_VERSION,
        "engine": "xgboost" if _MODEL_BUNDLE else "rule-based",
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/score", response_model=ScoreResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("120/minute")
def score(request: Request, payload: ScoreRequest):
    t0 = time.time()
    try:
        features = fetch_features(app.state.db, payload.customer_id)
        if _MODEL_BUNDLE is not None:
            score_val, reasons = score_xgboost(_MODEL_BUNDLE, features, payload)
        else:
            score_val, reasons = score_rulebased(features, payload)

        decision = decide(score_val)
        now = datetime.now(timezone.utc)

        app.state.db.fraud_alerts.insert_one({
            "transaction_id": payload.transaction_id,
            "customer_id": payload.customer_id,
            "merchant_id": payload.merchant_id,
            "score": score_val,
            "decision": decision,
            "model_version": MODEL_VERSION,
            "features_snapshot": features,
            "reasons": reasons,
            "created_at": now,
        })

        REQUEST_COUNT.labels(decision=decision).inc()
        logger.info("scored tx=%s score=%.3f decision=%s",
                    payload.transaction_id, score_val, decision)
        return ScoreResponse(
            transaction_id=payload.transaction_id,
            score=score_val,
            decision=decision,
            model_version=MODEL_VERSION,
            reasons=reasons,
            scored_at=now,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("scoring failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        REQUEST_LATENCY.observe(time.time() - t0)
