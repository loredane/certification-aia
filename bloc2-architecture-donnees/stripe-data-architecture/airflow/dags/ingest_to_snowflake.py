"""
DAG: ingest_to_snowflake
Schedule: @hourly
Pipeline ELT : PostgreSQL OLTP → S3 (MinIO) → Snowflake RAW
Orchestre les sync Airbyte via API.

FIX v3-hauts :
- Remplacé la task `trigger_transform` (BashOperator echo bidon) par un
  vrai TriggerDagRunOperator qui déclenche le DAG transform_dbt.
- Retiré `sla` de default_args (déprécié Airflow 2.9+).
- Ajouté l'authentification Airbyte OSS (token via application client_id/secret).

DAMA-DMBOK2 ch.8 §1.3.1 — ELT pattern
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

default_args = {
    "owner": "data_engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
    "email_on_failure": True,
    "email": ["data-alerts@stripe-demo.local"],
}

with DAG(
    dag_id="ingest_to_snowflake",
    description="ELT PostgreSQL -> S3 -> Snowflake via Airbyte",
    schedule="@hourly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["elt", "airbyte", "snowflake", "bloc2"],
) as dag:

    start = EmptyOperator(task_id="start")

    def get_airbyte_token(airbyte_url, client_id, client_secret):
        """
        Recupere un bearer token Airbyte OSS (Keycloak) via l'endpoint
        /api/v1/applications/token. Obligatoire depuis Airbyte 0.63+.
        """
        import requests
        resp = requests.post(
            f"{airbyte_url}/api/v1/applications/token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def trigger_airbyte_sync(connection_id, **context):
        """
        Declenche un sync Airbyte via son API REST authentifiee.
        Variables Airflow attendues :
          - airbyte_url          (ex: http://host.docker.internal:8000)
          - airbyte_client_id
          - airbyte_client_secret
        """
        import os
        import time
        import requests
        from airflow.models import Variable

        airbyte_url = Variable.get(
            "airbyte_url",
            default_var=os.environ.get("AIRBYTE_URL", "http://host.docker.internal:8000"),
        )
        client_id = Variable.get("airbyte_client_id", default_var="")
        client_secret = Variable.get("airbyte_client_secret", default_var="")

        headers = {"Content-Type": "application/json"}
        if client_id and client_secret:
            headers["Authorization"] = (
                f"Bearer {get_airbyte_token(airbyte_url, client_id, client_secret)}"
            )

        # Trigger sync
        resp = requests.post(
            f"{airbyte_url}/api/v1/connections/sync",
            json={"connectionId": connection_id},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        job_id = resp.json()["job"]["id"]
        print(f"Airbyte job {job_id} triggered for connection {connection_id}")

        # Poll status
        for _ in range(60):  # 30 min timeout
            time.sleep(30)
            s = requests.post(
                f"{airbyte_url}/api/v1/jobs/get",
                json={"id": job_id},
                headers=headers,
                timeout=30,
            )
            status = s.json()["job"]["status"]
            print(f"Job {job_id} status: {status}")
            if status in ("succeeded", "failed", "cancelled"):
                if status != "succeeded":
                    raise RuntimeError(f"Airbyte job {job_id} ended with status {status}")
                return
        raise TimeoutError(f"Airbyte job {job_id} did not finish in 30 min")

    sync_postgres_to_s3 = PythonOperator(
        task_id="sync_postgres_to_s3",
        python_callable=trigger_airbyte_sync,
        op_kwargs={"connection_id": "{{ var.value.airbyte_pg_to_s3 }}"},
    )

    sync_s3_to_snowflake = PythonOperator(
        task_id="sync_s3_to_snowflake",
        python_callable=trigger_airbyte_sync,
        op_kwargs={"connection_id": "{{ var.value.airbyte_s3_to_snowflake }}"},
    )

    check_freshness = BashOperator(
        task_id="check_snowflake_freshness",
        bash_command=(
            "cd /opt/airflow/dbt/stripe_analytics && "
            "dbt source freshness --profiles-dir /opt/airflow/dbt --target dev"
        ),
    )

    # FIX v3-hauts: vrai TriggerDagRunOperator (avant : BashOperator echo bidon)
    trigger_transform = TriggerDagRunOperator(
        task_id="trigger_transform_dbt",
        trigger_dag_id="transform_dbt",
        wait_for_completion=False,   # n'attend pas la fin du transform
        reset_dag_run=True,
        conf={"triggered_by": "ingest_to_snowflake", "run_id": "{{ run_id }}"},
    )

    end = EmptyOperator(task_id="end")

    start >> sync_postgres_to_s3 >> sync_s3_to_snowflake >> check_freshness >> trigger_transform >> end
