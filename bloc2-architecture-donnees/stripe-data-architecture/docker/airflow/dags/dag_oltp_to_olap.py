"""
DAG : OLTP → OLAP quotidien
Extract depuis PostgreSQL, transform via dbt, load ClickHouse
DAMA-DMBOK2 ch.8 §1.3 : ELT pattern, data quality checks
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator

default_args = {
    "owner": "data-eng",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "email": ["data-alerts@stripe-fiction.com"],
}

with DAG(
    dag_id="dag_oltp_to_olap_daily",
    default_args=default_args,
    description="ELT quotidien OLTP PostgreSQL → OLAP ClickHouse",
    schedule_interval="0 2 * * *",  # 2h du matin UTC
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["stripe", "elt", "olap"],
) as dag:

    # =========================================================================
    # 1. EXTRACT : Snapshot des transactions de J-1
    # =========================================================================
    extract_transactions = PostgresOperator(
        task_id="extract_transactions_d1",
        postgres_conn_id="postgres_oltp",
        sql="""
            COPY (
                SELECT transaction_id, merchant_id, customer_id, payment_method_id,
                       amount_minor, currency_code, status, fraud_score, fraud_decision,
                       created_at
                FROM core.transaction
                WHERE created_at >= (CURRENT_DATE - INTERVAL '1 day')::timestamptz
                  AND created_at <  CURRENT_DATE::timestamptz
            ) TO '/tmp/transactions_{{ ds_nodash }}.csv' WITH CSV HEADER;
        """,
    )

    # =========================================================================
    # 2. LOAD raw dans ClickHouse (staging)
    # =========================================================================
    load_staging = BashOperator(
        task_id="load_staging_clickhouse",
        bash_command="""
            clickhouse-client --host=clickhouse --query="
                INSERT INTO stripe_olap.stg_transaction
                FORMAT CSVWithNames
            " < /tmp/transactions_{{ ds_nodash }}.csv
        """,
    )

    # =========================================================================
    # 3. TRANSFORM : dbt run marts (revenue, fraud, segmentation)
    # =========================================================================
    dbt_run = BashOperator(
        task_id="dbt_run_marts",
        bash_command="""
            cd /usr/app/stripe_analytics &&
            dbt run --select marts --profiles-dir /root/.dbt
        """,
    )

    # =========================================================================
    # 4. DATA QUALITY : tests dbt (not_null, unique, relationships)
    # DAMA ch.13 : Data Quality
    # =========================================================================
    dbt_test = BashOperator(
        task_id="dbt_test_quality",
        bash_command="""
            cd /usr/app/stripe_analytics &&
            dbt test --select marts --profiles-dir /root/.dbt
        """,
    )

    # =========================================================================
    # 5. CHECK BUSINESS : revenue cohérence OLTP vs OLAP
    # =========================================================================
    def reconcile_revenue(**ctx):
        """Vérifie que le revenue OLAP correspond au revenue OLTP (tolérance 0.01%)"""
        from airflow.providers.postgres.hooks.postgres import PostgresHook
        import subprocess

        pg = PostgresHook(postgres_conn_id="postgres_oltp")
        oltp_revenue = pg.get_first("""
            SELECT COALESCE(SUM(amount_minor), 0)
            FROM core.transaction
            WHERE status = 'succeeded'
              AND created_at >= (CURRENT_DATE - INTERVAL '1 day')::timestamptz
              AND created_at <  CURRENT_DATE::timestamptz
        """)[0]

        result = subprocess.run(
            ["clickhouse-client", "--host=clickhouse", "--query",
             "SELECT SUM(gross_revenue_eur * 100) "
             "FROM stripe_olap.fact_daily_revenue "
             "WHERE date_id = toYYYYMMDD(yesterday())"],
            capture_output=True, text=True
        )
        olap_revenue = float(result.stdout.strip() or 0)

        diff_pct = abs(oltp_revenue - olap_revenue) / max(oltp_revenue, 1) * 100
        if diff_pct > 0.01:
            raise ValueError(f"Reconciliation failed: OLTP={oltp_revenue} vs OLAP={olap_revenue} ({diff_pct:.3f}%)")
        print(f"✓ Reconciliation OK: diff={diff_pct:.4f}%")

    reconcile = PythonOperator(
        task_id="reconcile_revenue",
        python_callable=reconcile_revenue,
    )

    # =========================================================================
    # 6. NOTIFY : Slack alert si succès + push metric
    # =========================================================================
    notify_success = BashOperator(
        task_id="notify_success",
        bash_command="""
            echo "[{{ ds }}] ELT OLTP→OLAP terminé — dbt run + tests + reconciliation OK"
        """,
    )

    # DAG lineage
    extract_transactions >> load_staging >> dbt_run >> dbt_test >> reconcile >> notify_success
