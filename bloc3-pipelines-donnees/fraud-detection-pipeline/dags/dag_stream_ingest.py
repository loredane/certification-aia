"""
DAG Airflow : ingestion temps réel des paiements

Pipeline ETL qui tourne chaque minute :
  Extract  -> appel API payments
  Transform -> validation qualité + prédiction ML
  Load     -> insertion PostgreSQL + alerte si fraude
"""
from datetime import datetime, timedelta
import logging
import time

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago

import sys
sys.path.insert(0, "/opt/airflow")

logger = logging.getLogger(__name__)

default_args = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=5),
}

dag = DAG(
    dag_id="stream_ingest",
    default_args=default_args,
    description="ETL temps réel : API -> Validate -> Predict -> PostgreSQL",
    schedule_interval="*/1 * * * *",
    start_date=days_ago(1),
    catchup=False,
    max_active_runs=1,
    tags=["fraud-detection", "real-time", "etl"],
)


def task_extract(**context):
    """Récupère les transactions depuis l'API temps réel."""
    from src.utils.api_client import fetch_current_transactions

    transactions = fetch_current_transactions()

    if not transactions:
        logger.warning("Aucune transaction récupérée")
        context["ti"].xcom_push(key="transactions", value=[])
        context["ti"].xcom_push(key="extract_count", value=0)
        return

    logger.info(f"{len(transactions)} transactions extraites")
    context["ti"].xcom_push(key="transactions", value=transactions)
    context["ti"].xcom_push(key="extract_count", value=len(transactions))


def task_validate(**context):
    """Valide chaque transaction (schéma + règles métier). Les rejetées vont en DLQ."""
    from src.data_quality.validators import DataQualityValidator, send_to_dead_letter_queue

    transactions = context["ti"].xcom_pull(key="transactions", task_ids="extract")
    if not transactions:
        context["ti"].xcom_push(key="valid_transactions", value=[])
        return

    validator = DataQualityValidator()
    valid = []
    rejected = 0

    for txn in transactions:
        ok, errors = validator.validate_transaction(txn)
        if ok:
            txn["data_quality_status"] = "valid"
            valid.append(txn)
        else:
            txn["data_quality_status"] = "rejected"
            rejected += 1
            send_to_dead_letter_queue(txn, "validation_error", "; ".join(errors))

    try:
        validator.save_results_to_db()
    except Exception as e:
        logger.warning(f"Impossible de sauvegarder les logs DQ: {e}")

    logger.info(f"Validation: {len(valid)} valides, {rejected} rejetées")
    context["ti"].xcom_push(key="valid_transactions", value=valid)
    context["ti"].xcom_push(key="rejected_count", value=rejected)


def task_predict(**context):
    """Applique le modèle ML sur les transactions validées."""
    from src.ml.predict import predict_batch

    valid = context["ti"].xcom_pull(key="valid_transactions", task_ids="validate")
    if not valid:
        context["ti"].xcom_push(key="predicted_transactions", value=[])
        return

    predicted = predict_batch(valid)
    frauds = [t for t in predicted if t.get("is_fraud_predicted")]
    logger.info(f"{len(predicted)} prédictions, {len(frauds)} fraudes détectées")

    context["ti"].xcom_push(key="predicted_transactions", value=predicted)
    context["ti"].xcom_push(key="fraud_transactions", value=frauds)


def task_load(**context):
    """Insère les transactions enrichies dans PostgreSQL."""
    import psycopg2
    from config.settings import DB_CONFIG
    from src.database.queries import INSERT_TRANSACTION

    predicted = context["ti"].xcom_pull(key="predicted_transactions", task_ids="predict")
    if not predicted:
        return

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    inserted = 0

    for txn in predicted:
        try:
            cur.execute(INSERT_TRANSACTION, txn)
            if cur.fetchone():
                inserted += 1
        except Exception as e:
            logger.error(f"Erreur insertion {txn.get('trans_num')}: {e}")
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"{inserted}/{len(predicted)} transactions insérées")
    context["ti"].xcom_push(key="inserted_count", value=inserted)


def task_notify(**context):
    """Envoie une alerte pour chaque fraude détectée."""
    from src.notifications.alerting import send_fraud_alert

    frauds = context["ti"].xcom_pull(key="fraud_transactions", task_ids="predict")
    if not frauds:
        return

    for fraud in frauds:
        send_fraud_alert(fraud)
    logger.info(f"{len(frauds)} alertes envoyées")


def task_log_pipeline(**context):
    """Enregistre les métriques d'exécution dans pipeline_logs."""
    import psycopg2
    from config.settings import DB_CONFIG
    from src.database.queries import INSERT_PIPELINE_LOG

    extract_count = context["ti"].xcom_pull(key="extract_count", task_ids="extract") or 0
    rejected = context["ti"].xcom_pull(key="rejected_count", task_ids="validate") or 0

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(INSERT_PIPELINE_LOG, {
            "dag_id": "stream_ingest",
            "task_id": "full_pipeline",
            "execution_date": context["execution_date"],
            "status": "success",
            "records_processed": extract_count,
            "records_failed": rejected,
            "duration_seconds": 0,
            "error_message": None,
        })
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Erreur log pipeline: {e}")


# Tasks et dépendances
extract = PythonOperator(task_id="extract", python_callable=task_extract, dag=dag)
validate = PythonOperator(task_id="validate", python_callable=task_validate, dag=dag)
predict = PythonOperator(task_id="predict", python_callable=task_predict, dag=dag)
load = PythonOperator(task_id="load", python_callable=task_load, dag=dag)
notify = PythonOperator(task_id="notify", python_callable=task_notify, dag=dag)
log_pipeline = PythonOperator(task_id="log_pipeline", python_callable=task_log_pipeline, dag=dag)

# Extract -> Validate -> Predict -> Load -> [Notify, Log]
extract >> validate >> predict >> load >> [notify, log_pipeline]
