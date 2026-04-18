"""
Entrainement du modèle de détection de fraude.

On utilise un RandomForest avec class_weight='balanced' pour
gérer le déséquilibre du dataset (~0.5% de fraudes).
Le modèle est sauvé dans MLflow si disponible, sinon en local avec joblib.

Note : le modèle ML est secondaire dans ce projet,
la priorité est le pipeline de données.
"""
import os
import sys
import logging
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, precision_score, recall_score, f1_score, roc_auc_score
from sklearn.pipeline import Pipeline
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import (
    TRAIN_DATA_PATH, TRAIN_DATA_URL, MODEL_DIR,
    MODEL_FEATURES, TARGET_COLUMN, MLFLOW_TRACKING_URI,
    MLFLOW_EXPERIMENT_NAME, MODEL_NAME
)
from src.ml.preprocessing import build_preprocessing_pipeline

logger = logging.getLogger(__name__)


def download_training_data():
    """Télécharge le CSV si pas déjà présent."""
    if TRAIN_DATA_PATH.exists():
        logger.info(f"Dataset déjà présent: {TRAIN_DATA_PATH}")
        return

    logger.info("Téléchargement du dataset...")
    os.makedirs(TRAIN_DATA_PATH.parent, exist_ok=True)
    df = pd.read_csv(TRAIN_DATA_URL)
    df.to_csv(TRAIN_DATA_PATH, index=False)
    logger.info(f"Sauvegardé: {TRAIN_DATA_PATH} ({len(df)} lignes)")


def train_model(use_mlflow=True):
    """Entraine le pipeline complet (preprocessing + classifier) et retourne les métriques."""

    # 1. Charger les données
    download_training_data()
    logger.info("Chargement du dataset...")
    df = pd.read_csv(TRAIN_DATA_PATH)
    logger.info(f"{len(df)} transactions, {df[TARGET_COLUMN].sum()} fraudes "
                f"({100*df[TARGET_COLUMN].mean():.2f}%)")

    # 2. Séparer features / target
    X = df[MODEL_FEATURES].fillna(0)
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    logger.info(f"Train: {len(X_train)}, Test: {len(X_test)}")

    # 3. Construire le pipeline complet
    preprocessing = build_preprocessing_pipeline()

    full_pipeline = Pipeline([
        ("preprocessing", preprocessing),
        ("classifier", RandomForestClassifier(
            n_estimators=100,
            max_depth=15,
            min_samples_split=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )),
    ])

    # 4. Entrainer
    logger.info("Entrainement en cours...")
    full_pipeline.fit(X_train, y_train)

    # 5. Evaluer
    y_pred = full_pipeline.predict(X_test)
    y_proba = full_pipeline.predict_proba(X_test)[:, 1]

    metrics = {
        "precision": precision_score(y_test, y_pred),
        "recall": recall_score(y_test, y_pred),
        "f1_score": f1_score(y_test, y_pred),
        "roc_auc": roc_auc_score(y_test, y_proba),
    }

    logger.info("Métriques:")
    for k, v in metrics.items():
        logger.info(f"  {k}: {v:.4f}")

    print("\n" + classification_report(y_test, y_pred, target_names=["Légitime", "Fraude"]))

    # 6. Sauvegarder
    if use_mlflow:
        _save_with_mlflow(full_pipeline, metrics, X_train)
    else:
        _save_local(full_pipeline)

    return full_pipeline, metrics


def _save_with_mlflow(pipeline, metrics, X_train):
    """Sauvegarde dans MLflow si le serveur est disponible."""
    try:
        import mlflow
        import mlflow.sklearn

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

        with mlflow.start_run(run_name="fraud_detection_rf") as run:
            mlflow.log_param("model_type", "RandomForestClassifier")
            mlflow.log_param("n_estimators", 100)
            mlflow.log_param("max_depth", 15)
            mlflow.log_param("features", str(MODEL_FEATURES))
            mlflow.log_param("train_size", len(X_train))

            for k, v in metrics.items():
                mlflow.log_metric(k, v)

            mlflow.sklearn.log_model(
                pipeline,
                artifact_path="model",
                registered_model_name=MODEL_NAME,
            )
            logger.info(f"Modèle sauvé dans MLflow (run: {run.info.run_id})")

    except Exception as e:
        logger.warning(f"MLflow non disponible ({e}), sauvegarde locale")
        _save_local(pipeline)


def _save_local(pipeline):
    """Sauvegarde locale avec joblib (fallback si pas de MLflow)."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = MODEL_DIR / "fraud_model.joblib"
    joblib.dump(pipeline, path)
    logger.info(f"Modèle sauvé: {path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    train_model(use_mlflow=False)
