"""
Module de prédiction en production.
Charge le modèle (MLflow ou local) et prédit si une transaction est frauduleuse.
"""
import os
import sys
import logging
import pandas as pd
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import (
    MODEL_DIR, MODEL_FEATURES, FRAUD_PROBABILITY_THRESHOLD,
    MLFLOW_TRACKING_URI, MODEL_NAME
)

logger = logging.getLogger(__name__)

# On cache le modèle pour pas le recharger à chaque transaction
_model_cache = None
_version_cache = None


def load_model():
    """
    Charge le modèle. Essaie MLflow d'abord, sinon fichier local.
    Le modèle est mis en cache pour les appels suivants.
    """
    global _model_cache, _version_cache

    if _model_cache is not None:
        return _model_cache, _version_cache

    # Essayer MLflow
    try:
        import mlflow.sklearn
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        _model_cache = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}/latest")
        _version_cache = "mlflow-latest"
        logger.info(f"Modèle chargé depuis MLflow")
        return _model_cache, _version_cache
    except Exception as e:
        logger.info(f"MLflow pas dispo ({e}), on essaie en local")

    # Fallback local
    model_path = MODEL_DIR / "fraud_model.joblib"
    if model_path.exists():
        _model_cache = joblib.load(model_path)
        _version_cache = "local-joblib"
        logger.info(f"Modèle chargé: {model_path}")
        return _model_cache, _version_cache

    raise FileNotFoundError("Pas de modèle trouvé. Lancez d'abord: python src/ml/train.py")


def predict_fraud(transaction):
    """
    Prédit la probabilité de fraude pour une transaction.
    Retourne (probability, is_fraud).
    """
    model, version = load_model()

    # Préparer les features
    features = {}
    for col in MODEL_FEATURES:
        val = transaction.get(col, 0)
        try:
            features[col] = float(val) if val is not None else 0.0
        except (ValueError, TypeError):
            features[col] = 0.0

    X = pd.DataFrame([features])
    probability = float(model.predict_proba(X)[0, 1])
    is_fraud = probability >= FRAUD_PROBABILITY_THRESHOLD

    return probability, is_fraud


def predict_batch(transactions):
    """
    Prédit la fraude pour un batch de transactions.
    Enrichit chaque transaction avec fraud_probability et is_fraud_predicted.
    """
    model, version = load_model()
    results = []

    for txn in transactions:
        try:
            prob, is_fraud = predict_fraud(txn)
            txn["fraud_probability"] = round(prob, 4)
            txn["is_fraud_predicted"] = is_fraud
            txn["model_version"] = version
        except Exception as e:
            logger.error(f"Erreur prédiction {txn.get('trans_num')}: {e}")
            txn["fraud_probability"] = None
            txn["is_fraud_predicted"] = False
            txn["model_version"] = "error"
        results.append(txn)

    nb_frauds = sum(1 for t in results if t.get("is_fraud_predicted"))
    logger.info(f"Batch: {len(results)} transactions, {nb_frauds} fraudes")
    return results
