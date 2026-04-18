"""
DAG Airflow : réentrainement du modèle ML

Tourne une fois par semaine (dimanche 2h du matin).
Permet de garder le modèle à jour si les patterns de fraude évoluent.
"""
from datetime import timedelta
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
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "execution_timeout": timedelta(hours=1),
}

dag = DAG(
    dag_id="train_model",
    default_args=default_args,
    description="Réentrainement hebdomadaire du modèle",
    schedule_interval="0 2 * * 0",
    start_date=days_ago(7),
    catchup=False,
    tags=["fraud-detection", "ml", "training"],
)


def task_download_data(**context):
    from src.ml.train import download_training_data
    download_training_data()


def task_train(**context):
    from src.ml.train import train_model
    pipeline, metrics = train_model(use_mlflow=True)
    context["ti"].xcom_push(key="metrics", value=metrics)
    logger.info(f"Modèle entrainé, f1={metrics['f1_score']:.4f}")


def task_validate_model(**context):
    """Vérifie que les métriques du modèle dépassent les seuils minimum."""
    metrics = context["ti"].xcom_pull(key="metrics", task_ids="train")

    if metrics["recall"] < 0.5:
        raise ValueError(f"Recall trop bas: {metrics['recall']:.4f}")
    if metrics["precision"] < 0.3:
        raise ValueError(f"Precision trop basse: {metrics['precision']:.4f}")

    logger.info("Modèle validé, métriques OK")


download = PythonOperator(task_id="download_data", python_callable=task_download_data, dag=dag)
train = PythonOperator(task_id="train", python_callable=task_train, dag=dag)
validate = PythonOperator(task_id="validate_model", python_callable=task_validate_model, dag=dag)

download >> train >> validate
