"""
Pipeline de preprocessing pour le modèle de fraude.
On utilise un pipeline sklearn pour que le preprocessing soit
identique en entrainement et en prédiction.
"""
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.base import BaseEstimator, TransformerMixin

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import MODEL_FEATURES


class FeatureEngineer(BaseEstimator, TransformerMixin):
    """
    Crée des features supplémentaires à partir des données brutes :
    - distance entre la transaction et le commerçant
    - log du montant (pour réduire l'asymétrie de la distribution)
    - heure de la journée encodée en sin/cos (cyclicité)
    """

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        df = pd.DataFrame(X, columns=MODEL_FEATURES)

        # Distance transaction <-> commerçant (approximation euclidienne)
        df["distance_to_merchant"] = np.sqrt(
            (df["lat"] - df["merch_lat"]) ** 2 +
            (df["long"] - df["merch_long"]) ** 2
        )

        # Log du montant
        df["log_amt"] = np.log1p(df["amt"])

        # Heure depuis unix_time
        df["hour"] = (df["unix_time"] % 86400) // 3600
        df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
        df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)

        output_cols = [
            "amt", "log_amt", "city_pop",
            "distance_to_merchant",
            "hour_sin", "hour_cos",
        ]
        return df[output_cols].values


def build_preprocessing_pipeline():
    """Retourne le pipeline complet : feature engineering + scaling."""
    return Pipeline([
        ("feature_engineering", FeatureEngineer()),
        ("scaler", StandardScaler()),
    ])


def prepare_features(df):
    """Prépare un dataframe brut pour la prédiction (conversion de types + vérification)."""
    for col in ["amt", "lat", "long", "merch_lat", "merch_long"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["city_pop", "unix_time"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    missing = [c for c in MODEL_FEATURES if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes: {missing}")

    return df[MODEL_FEATURES]
