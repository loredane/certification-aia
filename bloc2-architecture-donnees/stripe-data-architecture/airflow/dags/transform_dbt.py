"""
DAG: transform_dbt
Schedule: @hourly (après ingest_to_snowflake)
Transforme RAW → STAGING → MARTS dans Snowflake via dbt.

DAMA-DMBOK2 ch.5 §1.3.4 — Dimensional modeling (star schema)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator

default_args = {
    "owner": "analytics_engineering",
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
    "email_on_failure": True,
    "email": ["analytics-alerts@stripe-demo.local"],
}

DBT_DIR = "/opt/airflow/dbt/stripe_analytics"
DBT_PROFILES = "/opt/airflow/dbt"

with DAG(
    dag_id="transform_dbt",
    description="dbt run + test on Snowflake (staging → marts)",
    # FIX v3-mediums #6 : schedule=None (trigger-only).
    # Le DAG ingest_to_snowflake termine par un TriggerDagRunOperator qui
    # déclenche ce DAG. Un ancien cron "15 * * * *" ne garantissait pas que
    # ingest soit terminé — risque de run dbt sur un RAW incomplet.
    # Peut aussi être déclenché manuellement depuis l'UI pour un replay.
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["dbt", "snowflake", "bloc2"],
) as dag:

    start = EmptyOperator(task_id="start")

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command=f"cd {DBT_DIR} && dbt deps --profiles-dir {DBT_PROFILES}",
    )

    dbt_run_staging = BashOperator(
        task_id="dbt_run_staging",
        bash_command=(
            f"cd {DBT_DIR} && "
            f"dbt run --select staging --profiles-dir {DBT_PROFILES} --target dev"
        ),
    )

    dbt_run_marts = BashOperator(
        task_id="dbt_run_marts",
        bash_command=(
            f"cd {DBT_DIR} && "
            f"dbt run --select marts --profiles-dir {DBT_PROFILES} --target dev"
        ),
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=(
            f"cd {DBT_DIR} && "
            f"dbt test --profiles-dir {DBT_PROFILES} --target dev"
        ),
    )

    dbt_docs = BashOperator(
        task_id="dbt_docs_generate",
        bash_command=(
            f"cd {DBT_DIR} && "
            f"dbt docs generate --profiles-dir {DBT_PROFILES} --target dev"
        ),
        trigger_rule="all_done",
    )

    end = EmptyOperator(task_id="end")

    start >> dbt_deps >> dbt_run_staging >> dbt_run_marts >> dbt_test >> dbt_docs >> end
