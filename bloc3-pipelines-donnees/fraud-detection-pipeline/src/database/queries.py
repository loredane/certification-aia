"""
Requêtes SQL utilisées dans le pipeline.
Centralisées ici pour pas les éparpiller dans les DAGs.
"""

# Insert une transaction avec sa prédiction
INSERT_TRANSACTION = """
    INSERT INTO transactions (
        trans_date_trans_time, cc_num, merchant, category, amt,
        first_name, last_name, gender, street, city, state, zip,
        lat, long, city_pop, job, dob, trans_num, unix_time,
        merch_lat, merch_long, fraud_probability, is_fraud_predicted,
        model_version, data_quality_status
    ) VALUES (
        %(trans_date_trans_time)s, %(cc_num)s, %(merchant)s, %(category)s, %(amt)s,
        %(first)s, %(last)s, %(gender)s, %(street)s, %(city)s, %(state)s, %(zip)s,
        %(lat)s, %(long)s, %(city_pop)s, %(job)s, %(dob)s, %(trans_num)s, %(unix_time)s,
        %(merch_lat)s, %(merch_long)s, %(fraud_probability)s, %(is_fraud_predicted)s,
        %(model_version)s, %(data_quality_status)s
    )
    ON CONFLICT (trans_num) DO NOTHING
    RETURNING id;
"""

# Résumé des transactions de la veille (pour le rapport quotidien)
DAILY_SUMMARY = """
    SELECT
        DATE(trans_date_trans_time) AS transaction_date,
        COUNT(*) AS total_transactions,
        SUM(CASE WHEN is_fraud_predicted THEN 1 ELSE 0 END) AS total_frauds,
        ROUND(
            100.0 * SUM(CASE WHEN is_fraud_predicted THEN 1 ELSE 0 END) / COUNT(*), 2
        ) AS fraud_rate_pct,
        ROUND(SUM(amt)::numeric, 2) AS total_amount,
        ROUND(SUM(CASE WHEN is_fraud_predicted THEN amt ELSE 0 END)::numeric, 2) AS fraud_amount
    FROM transactions
    WHERE DATE(ingested_at) = CURRENT_DATE
    GROUP BY DATE(trans_date_trans_time)
    ORDER BY transaction_date DESC
    LIMIT 1;
"""

# Liste des fraudes détectées la veille
DAILY_FRAUDS_DETAIL = """
    SELECT
        trans_date_trans_time, cc_num, merchant, category,
        amt, city, state, fraud_probability, trans_num
    FROM transactions
    WHERE is_fraud_predicted = TRUE
      AND DATE(ingested_at) = CURRENT_DATE
    ORDER BY fraud_probability DESC;
"""

# Top catégories les plus touchées par la fraude
TOP_FRAUD_CATEGORIES = """
    SELECT
        category,
        COUNT(*) AS fraud_count,
        ROUND(AVG(amt)::numeric, 2) AS avg_fraud_amount
    FROM transactions
    WHERE is_fraud_predicted = TRUE
      AND DATE(ingested_at) = CURRENT_DATE
    GROUP BY category
    ORDER BY fraud_count DESC
    LIMIT 10;
"""

INSERT_PIPELINE_LOG = """
    INSERT INTO pipeline_logs (
        dag_id, task_id, execution_date, status,
        records_processed, records_failed, duration_seconds, error_message
    ) VALUES (
        %(dag_id)s, %(task_id)s, %(execution_date)s, %(status)s,
        %(records_processed)s, %(records_failed)s, %(duration_seconds)s, %(error_message)s
    );
"""

INSERT_DQ_LOG = """
    INSERT INTO data_quality_logs (
        check_name, check_type, passed, details,
        records_checked, records_passed, pass_rate
    ) VALUES (
        %(check_name)s, %(check_type)s, %(passed)s, %(details)s,
        %(records_checked)s, %(records_passed)s, %(pass_rate)s
    );
"""

INSERT_DEAD_LETTER = """
    INSERT INTO dead_letter_queue (raw_data, error_type, error_message, source)
    VALUES (%(raw_data)s, %(error_type)s, %(error_message)s, %(source)s);
"""

# Pour le dashboard monitoring
PIPELINE_HEALTH_METRICS = """
    SELECT
        dag_id,
        COUNT(*) AS total_runs,
        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes,
        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failures,
        ROUND(AVG(duration_seconds)::numeric, 2) AS avg_duration,
        ROUND(AVG(records_processed)::numeric, 0) AS avg_records
    FROM pipeline_logs
    WHERE execution_date >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY dag_id;
"""
