"""
DAG : Calcul features ML horaires
Extract depuis OLTP → transform rolling windows → load MongoDB feature store
DAMA-DMBOK2 ch.8 + ML integration strategy
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "ml-eng",
    "depends_on_past": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
}

def compute_customer_features(**ctx):
    """Calcule les features agrégées par customer sur fenêtres rolling (7j, 30j, 180j)"""
    from airflow.providers.postgres.hooks.postgres import PostgresHook
    from pymongo import MongoClient
    import os

    pg = PostgresHook(postgres_conn_id="postgres_oltp")

    sql = """
    WITH tx AS (
        SELECT
            customer_id,
            created_at,
            amount_minor,
            status,
            merchant_id,
            (SELECT country_code FROM core.merchant m WHERE m.merchant_id = t.merchant_id) AS merchant_country
        FROM core.transaction t
        WHERE created_at >= NOW() - INTERVAL '180 days'
    ),
    features AS (
        SELECT
            customer_id,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')   AS tx_count_7d,
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days')  AS tx_count_30d,
            AVG(amount_minor / 100.0) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')  AS avg_amount_7d,
            AVG(amount_minor / 100.0) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS avg_amount_30d,
            COUNT(DISTINCT merchant_country) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days')  AS distinct_countries_30d,
            COUNT(DISTINCT merchant_id)       FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS distinct_merchants_30d,
            AVG(CASE WHEN status = 'failed' THEN 1.0 ELSE 0.0 END) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS failed_tx_rate_30d
        FROM tx
        GROUP BY customer_id
    )
    SELECT * FROM features
    """

    rows = pg.get_records(sql)

    mongo = MongoClient(
        f"mongodb://{os.getenv('MONGO_USER', 'stripe')}:{os.getenv('MONGO_PASSWORD', 'stripe_pwd')}@mongodb:27017/"
    )
    coll = mongo["stripe_nosql"]["ml_feature_store"]

    now = datetime.utcnow()
    operations = 0
    for r in rows:
        doc = {
            "customer_id": str(r[0]),
            "features_version": "v1.2",
            "computed_at": now,
            "transaction_features": {
                "tx_count_7d":             int(r[1] or 0),
                "tx_count_30d":            int(r[2] or 0),
                "avg_amount_7d":           float(r[3] or 0),
                "avg_amount_30d":          float(r[4] or 0),
                "distinct_countries_30d":  int(r[5] or 0),
                "distinct_merchants_30d":  int(r[6] or 0),
                "failed_tx_rate_30d":      float(r[7] or 0),
            },
        }
        coll.update_one(
            {"customer_id": doc["customer_id"]},
            {"$set": doc},
            upsert=True,
        )
        operations += 1

    print(f"✓ {operations} customer features upserted dans ml_feature_store")
    ctx["ti"].xcom_push(key="ops_count", value=operations)


def validate_feature_freshness(**ctx):
    """Vérifie qu'au moins 90% des customers actifs ont des features fraîches"""
    from pymongo import MongoClient
    import os
    mongo = MongoClient(
        f"mongodb://{os.getenv('MONGO_USER', 'stripe')}:{os.getenv('MONGO_PASSWORD', 'stripe_pwd')}@mongodb:27017/"
    )
    coll = mongo["stripe_nosql"]["ml_feature_store"]

    threshold = datetime.utcnow() - timedelta(hours=2)
    fresh = coll.count_documents({"computed_at": {"$gte": threshold}})
    total = coll.count_documents({})
    ratio = fresh / max(total, 1)

    if ratio < 0.9:
        raise ValueError(f"Feature freshness dégradé: {ratio:.2%} < 90%")
    print(f"✓ Feature freshness : {ratio:.2%} des customers ont des features <2h")


with DAG(
    dag_id="dag_ml_features_hourly",
    default_args=default_args,
    description="Calcul horaire des features ML → MongoDB feature store",
    schedule_interval="0 * * * *",  # Toutes les heures
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["stripe", "ml", "features"],
) as dag:

    compute_features = PythonOperator(
        task_id="compute_customer_features",
        python_callable=compute_customer_features,
    )

    validate_freshness = PythonOperator(
        task_id="validate_feature_freshness",
        python_callable=validate_feature_freshness,
    )

    compute_features >> validate_freshness
