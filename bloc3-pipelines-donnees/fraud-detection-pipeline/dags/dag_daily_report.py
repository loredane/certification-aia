"""
DAG Airflow : rapport quotidien (batch)

Tous les matins à 7h, on agrège les transactions de la veille
et on envoie un rapport par email.

C'est un processus ELT :
  Extract -> query PostgreSQL (transactions J-1)
  Load -> en mémoire dans Pandas
  Transform -> agrégation, KPIs, génération rapport HTML
"""
from datetime import datetime, timedelta
import json
import logging

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
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="daily_report",
    default_args=default_args,
    description="Rapport quotidien des transactions J-1",
    schedule_interval="0 7 * * *",  # tous les jours à 7h
    start_date=days_ago(1),
    catchup=False,
    tags=["fraud-detection", "batch", "reporting"],
)


def task_extract_daily_data(**context):
    """Récupère les stats de la veille depuis PostgreSQL."""
    import psycopg2
    import psycopg2.extras
    from config.settings import DB_CONFIG
    from src.database.queries import DAILY_SUMMARY, DAILY_FRAUDS_DETAIL, TOP_FRAUD_CATEGORIES

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(DAILY_SUMMARY)
    rows = cur.fetchall()
    summary = dict(rows[0]) if rows else {
        "total_transactions": 0, "total_frauds": 0,
        "fraud_rate_pct": 0, "total_amount": 0, "fraud_amount": 0,
    }

    cur.execute(DAILY_FRAUDS_DETAIL)
    frauds = [dict(r) for r in cur.fetchall()]

    cur.execute(TOP_FRAUD_CATEGORIES)
    categories = [dict(r) for r in cur.fetchall()]

    cur.close()
    conn.close()

    logger.info(f"J-1 : {summary.get('total_transactions', 0)} transactions, "
                f"{summary.get('total_frauds', 0)} fraudes")

    # Conversion pour XCom (Decimal -> float)
    def serialize(obj):
        if hasattr(obj, '__float__'):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    context["ti"].xcom_push(key="summary", value=json.loads(json.dumps(summary, default=serialize)))
    context["ti"].xcom_push(key="frauds_detail", value=json.loads(json.dumps(frauds, default=serialize)))
    context["ti"].xcom_push(key="top_categories", value=json.loads(json.dumps(categories, default=serialize)))


def task_generate_report(**context):
    """Génère le rapport HTML et l'envoie."""
    from src.notifications.alerting import send_daily_report

    summary = context["ti"].xcom_pull(key="summary", task_ids="extract_daily_data")
    frauds = context["ti"].xcom_pull(key="frauds_detail", task_ids="extract_daily_data")
    cats = context["ti"].xcom_pull(key="top_categories", task_ids="extract_daily_data")

    send_daily_report(summary or {}, frauds or [], cats or [])
    logger.info("Rapport envoyé")


def task_log_report(**context):
    """Log l'exécution."""
    import psycopg2
    from config.settings import DB_CONFIG
    from src.database.queries import INSERT_PIPELINE_LOG

    summary = context["ti"].xcom_pull(key="summary", task_ids="extract_daily_data") or {}

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(INSERT_PIPELINE_LOG, {
            "dag_id": "daily_report",
            "task_id": "full_report",
            "execution_date": context["execution_date"],
            "status": "success",
            "records_processed": summary.get("total_transactions", 0),
            "records_failed": 0,
            "duration_seconds": 0,
            "error_message": None,
        })
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Erreur log: {e}")


extract_daily = PythonOperator(task_id="extract_daily_data", python_callable=task_extract_daily_data, dag=dag)
generate_report = PythonOperator(task_id="generate_report", python_callable=task_generate_report, dag=dag)
log_report = PythonOperator(task_id="log_report", python_callable=task_log_report, dag=dag)

extract_daily >> generate_report >> log_report
