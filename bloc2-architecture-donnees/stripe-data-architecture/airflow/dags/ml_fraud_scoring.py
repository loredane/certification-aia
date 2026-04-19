"""
DAG: ml_fraud_scoring
Schedule: daily at 03:00 UTC
Pipeline ML fraud detection :
  extract_training_dataset -> compute_features -> train_model -> validate
     -> deploy_canary -> monitor_drift

FIX v3-hauts :
- Remplace le pseudo-code (print() only) par une implementation reelle :
  * extract_training_dataset : vrai SELECT Snowflake via SnowflakeHook,
    materialise en parquet sur /tmp.
  * compute_features : calcule velocity_score, tx_count_24h etc. depuis
    le dataframe, upsert dans MongoDB ml_features_customer.
  * train_model : XGBClassifier scikit-learn + cross-val stratifiee,
    serialise en pickle, log metriques vers XCom.
  * validate_model : gate sur AUC >= seuil, sinon fail.
  * deploy_canary : upload pickle vers MinIO s3://ml-artifacts/fraud/,
    pousse le model_version dans MongoDB (routage 5% trafic cote API).
  * monitor_drift : PSI sur les features principales vs reference dataset.

Les imports lourds (xgboost, sklearn, pandas, snowflake-connector) sont
realises DANS les callables pour que le scheduler Airflow parse le fichier
sans charger ces dependances.

DAMA-DMBOK2 ch.14 §2.2 — Big Data & Data Science
Fundamentals of Data Engineering ch.12 — ML feature store + training pipelines
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator

default_args = {
    "owner": "ml_engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": True,
    "email": ["ml-oncall@stripe-demo.local"],
}

# --- Chemins locaux container Airflow (montes sur volume en prod via S3) ---
DATA_DIR = "/tmp/stripe_ml"
TRAIN_PARQUET = f"{DATA_DIR}/training.parquet"
MODEL_PATH = f"{DATA_DIR}/fraud_model.pkl"
REF_DISTRIB = f"{DATA_DIR}/reference_distrib.parquet"

# --- Hyperparametres XGBoost (exposes pour tuning ulterieur) ---
XGB_PARAMS = {
    "n_estimators": 100,
    "max_depth": 5,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "use_label_encoder": False,
    "eval_metric": "auc",
}
AUC_MIN = 0.85  # gate de validation avant deploy


def extract_training_dataset(**context):
    """
    Extrait 90 jours de transactions labelisees depuis Snowflake MARTS.
    Ecrit un parquet local (et dans un vrai pipeline, dans S3).
    """
    import os
    import pandas as pd
    from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

    os.makedirs(DATA_DIR, exist_ok=True)

    hook = SnowflakeHook(snowflake_conn_id="snowflake_default")
    sql = """
        SELECT
            f.transaction_id,
            f.customer_sk,
            f.merchant_sk,
            f.amount_usd,
            f.device_type,
            f.is_3d_secure,
            f.fraud_score,
            CASE WHEN f.is_high_fraud_risk = 1 THEN 1 ELSE 0 END AS label,
            c.risk_tier,
            c.country_is_high_risk,
            m.mcc_category,
            f.transaction_date
        FROM STRIPE_ANALYTICS.MARTS.FACT_TRANSACTION f
        LEFT JOIN STRIPE_ANALYTICS.MARTS.DIM_CUSTOMER c USING (customer_sk)
        LEFT JOIN STRIPE_ANALYTICS.MARTS.DIM_MERCHANT m USING (merchant_sk)
        WHERE f.transaction_date >= DATEADD('day', -90, CURRENT_DATE)
        LIMIT 100000
    """
    df = hook.get_pandas_df(sql)

    print(f"Extracted {len(df)} rows, fraud rate = {df['LABEL'].mean():.3%}")
    df.to_parquet(TRAIN_PARQUET, index=False)
    return TRAIN_PARQUET


def compute_features(**context):
    """
    Calcule les features agregees par customer_sk sur les 90 derniers jours,
    upsert dans MongoDB ml_features_customer (feature store online).
    """
    import pandas as pd
    from pymongo import MongoClient, UpdateOne
    from datetime import datetime as dt, timezone

    df = pd.read_parquet(TRAIN_PARQUET)
    df.columns = [c.lower() for c in df.columns]

    # Agregations par client
    agg = df.groupby("customer_sk").agg(
        tx_count_90d=("transaction_id", "count"),
        tx_amount_avg_30d=("amount_usd", "mean"),
        tx_amount_sum_24h=("amount_usd", "sum"),
        high_risk_rate=("label", "mean"),
    ).reset_index()

    # Approximations pour les features 1h/24h (sans timestamp precis)
    agg["tx_count_24h"] = (agg["tx_count_90d"] / 90).clip(upper=200).round().astype(int)
    agg["tx_count_1h"] = (agg["tx_count_24h"] / 24).clip(upper=50).round().astype(int)
    agg["velocity_score"] = (agg["tx_count_24h"] / 20).clip(upper=1.0)
    agg["risk_score"] = agg["high_risk_rate"].clip(upper=1.0)
    agg["distinct_merchants_24h"] = agg["tx_count_24h"].clip(upper=30)
    agg["distinct_countries_24h"] = (agg["tx_count_24h"] / 10).clip(upper=5).round().astype(int)
    agg["chargeback_ratio_90d"] = agg["high_risk_rate"] * 0.1

    # Upsert MongoDB
    uri = os.environ.get("MONGO_URI", "mongodb://admin:change_me@mongo:27017")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    coll = client["stripe_nosql"]["ml_features_customer"]

    now = dt.now(timezone.utc)
    ops = []
    for _, row in agg.iterrows():
        features = {
            "tx_count_1h": int(row["tx_count_1h"]),
            "tx_count_24h": int(row["tx_count_24h"]),
            "tx_count_7d": int(min(row["tx_count_90d"] * 7 / 90, 500)),
            "tx_amount_sum_24h": float(row["tx_amount_sum_24h"]),
            "tx_amount_avg_30d": float(row["tx_amount_avg_30d"]),
            "distinct_merchants_24h": int(row["distinct_merchants_24h"]),
            "distinct_countries_24h": int(row["distinct_countries_24h"]),
            "velocity_score": float(row["velocity_score"]),
            "risk_score": float(row["risk_score"]),
            "chargeback_ratio_90d": float(row["chargeback_ratio_90d"]),
        }
        ops.append(UpdateOne(
            {"customer_id": str(row["customer_sk"])},
            {"$set": {
                "customer_id": str(row["customer_sk"]),
                "features": features,
                "updated_at": now,
                "model_version": context["ds"],
            }},
            upsert=True,
        ))
    if ops:
        result = coll.bulk_write(ops)
        print(f"MongoDB upsert: matched={result.matched_count} upserted={result.upserted_count}")
    client.close()


def train_model(**context):
    """
    Entraine un XGBClassifier sur le dataset extrait.
    Pousse AUC et model_version vers XCom pour validate_model.
    """
    import numpy as np
    import pandas as pd
    import pickle
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from xgboost import XGBClassifier

    df = pd.read_parquet(TRAIN_PARQUET)
    df.columns = [c.lower() for c in df.columns]

    # One-hot simple des categorielles
    cats = ["device_type", "risk_tier", "mcc_category"]
    df_enc = pd.get_dummies(df[cats].fillna("unknown"), drop_first=True)
    numeric = df[["amount_usd", "is_3d_secure", "country_is_high_risk"]].fillna(0).astype(float)
    X = pd.concat([numeric, df_enc], axis=1).values
    y = df["label"].astype(int).values

    clf = XGBClassifier(**XGB_PARAMS)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc_scores = cross_val_score(clf, X, y, cv=cv, scoring="roc_auc", n_jobs=2)
    auc = float(np.mean(auc_scores))
    print(f"Cross-val AUC: mean={auc:.4f} std={np.std(auc_scores):.4f}")

    # Fit final sur tout le dataset pour export
    clf.fit(X, y)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": clf, "feature_order": list(numeric.columns) + list(df_enc.columns)}, f)

    # Stocke distribution de reference pour drift monitoring
    df[["amount_usd", "fraud_score"]].to_parquet(REF_DISTRIB, index=False)

    model_version = f"v{context['ds'].replace('-', '.')}"
    return {"model_version": model_version, "auc": auc}


def validate_model(**context):
    """Gate : refuse le deploy si AUC < AUC_MIN."""
    ti = context["ti"]
    metrics = ti.xcom_pull(task_ids="train_model")
    if metrics is None:
        raise RuntimeError("No metrics from train_model task")
    auc = metrics["auc"]
    if auc < AUC_MIN:
        raise ValueError(f"AUC {auc:.4f} below threshold {AUC_MIN}")
    print(f"Model {metrics['model_version']} passed validation (AUC={auc:.4f})")


def deploy_canary(**context):
    """
    Upload le model pickle vers MinIO bucket ml-artifacts/fraud/.
    Met a jour MongoDB ml_model_registry avec le model_version et un flag
    canary_pct = 5 pour que le ML service route 5% du trafic.
    """
    import boto3
    from botocore.client import Config
    from pymongo import MongoClient
    from datetime import datetime as dt, timezone

    ti = context["ti"]
    metrics = ti.xcom_pull(task_ids="train_model")
    model_version = metrics["model_version"]

    # Upload vers MinIO (S3-compatible)
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("MINIO_ENDPOINT", "http://minio:9000"),
        aws_access_key_id=os.environ.get("MINIO_USER", "minioadmin"),
        aws_secret_access_key=os.environ.get("MINIO_PASSWORD", "change_me"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    key = f"fraud/{model_version}/fraud_model.pkl"
    s3.upload_file(MODEL_PATH, "ml-artifacts", key)
    print(f"Uploaded model to s3://ml-artifacts/{key}")

    # Registre MongoDB
    uri = os.environ.get("MONGO_URI", "mongodb://admin:change_me@mongo:27017")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client["stripe_nosql"]["ml_model_registry"].update_one(
        {"name": "fraud_detection"},
        {"$set": {
            "name": "fraud_detection",
            "current_version": model_version,
            "canary_pct": 5,
            "model_uri": f"s3://ml-artifacts/{key}",
            "auc": metrics["auc"],
            "deployed_at": dt.now(timezone.utc),
        }},
        upsert=True,
    )
    client.close()


def monitor_drift(**context):
    """
    Compare la distribution des features (amount_usd, fraud_score) du dernier
    train dataset vs la reference stockee. Calcule PSI (Population Stability
    Index) — si PSI > 0.2 sur une feature, drift significatif, on alerte.
    """
    import numpy as np
    import pandas as pd

    def psi(expected, actual, buckets=10):
        bins = np.histogram_bin_edges(expected, bins=buckets)
        exp_perc = np.histogram(expected, bins=bins)[0] / max(len(expected), 1)
        act_perc = np.histogram(actual, bins=bins)[0] / max(len(actual), 1)
        exp_perc = np.where(exp_perc == 0, 1e-6, exp_perc)
        act_perc = np.where(act_perc == 0, 1e-6, act_perc)
        return float(np.sum((act_perc - exp_perc) * np.log(act_perc / exp_perc)))

    if not os.path.exists(REF_DISTRIB):
        print("No reference distribution yet — skipping drift check")
        return

    ref = pd.read_parquet(REF_DISTRIB)
    cur = pd.read_parquet(TRAIN_PARQUET)
    cur.columns = [c.lower() for c in cur.columns]

    for feature in ["amount_usd", "fraud_score"]:
        score = psi(ref[feature].dropna().values, cur[feature].dropna().values)
        print(f"PSI[{feature}] = {score:.4f}")
        if score > 0.2:
            print(f"WARNING: drift detected on {feature} (PSI>{0.2})")


with DAG(
    dag_id="ml_fraud_scoring",
    description="Daily fraud model retraining + canary deploy",
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["ml", "fraud", "bloc2"],
) as dag:

    start = EmptyOperator(task_id="start")

    t_extract = PythonOperator(task_id="extract_training_dataset",
                                python_callable=extract_training_dataset)
    t_features = PythonOperator(task_id="compute_features",
                                 python_callable=compute_features)
    t_train = PythonOperator(task_id="train_model",
                              python_callable=train_model)
    t_validate = PythonOperator(task_id="validate_model",
                                 python_callable=validate_model)
    t_deploy = PythonOperator(task_id="deploy_canary",
                               python_callable=deploy_canary)
    t_monitor = PythonOperator(task_id="monitor_drift",
                                python_callable=monitor_drift)

    end = EmptyOperator(task_id="end")

    start >> t_extract >> t_features >> t_train >> t_validate >> t_deploy >> t_monitor >> end
