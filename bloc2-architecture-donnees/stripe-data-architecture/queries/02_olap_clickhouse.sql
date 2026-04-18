-- =============================================================================
-- Livrable 8 — Requêtes SQL analytiques sur OLAP ClickHouse
-- Cas business : revenue, segmentation, performance produit, fraud analysis
-- =============================================================================

USE stripe_olap;

-- -----------------------------------------------------------------------------
-- Q1 — Revenue journalier des 30 derniers jours (utilise la materialized view)
-- -----------------------------------------------------------------------------
SELECT
    toDate(date_id)                        AS day,
    country_code,
    SUM(transaction_count)                 AS tx_count,
    ROUND(SUM(gross_revenue_eur), 2)       AS gross_revenue_eur,
    ROUND(SUM(net_revenue_eur), 2)         AS net_revenue_eur,
    ROUND(AVG(success_rate) * 100, 2)      AS avg_success_rate_pct
FROM fact_daily_revenue
WHERE toDate(date_id) >= today() - 30
GROUP BY day, country_code
ORDER BY day DESC, gross_revenue_eur DESC;


-- -----------------------------------------------------------------------------
-- Q2 — Top 20 merchants par revenue (Q en cours)
-- -----------------------------------------------------------------------------
SELECT
    m.business_name,
    m.country_code,
    SUM(f.transaction_count)                   AS total_tx,
    ROUND(SUM(f.gross_revenue_eur), 2)         AS revenue_eur
FROM fact_daily_revenue f
    JOIN dim_merchant m ON m.merchant_sk = f.merchant_sk
WHERE toDate(f.date_id) >= toStartOfQuarter(today())
  AND m.is_current = 1
GROUP BY m.merchant_sk, m.business_name, m.country_code
ORDER BY revenue_eur DESC
LIMIT 20;


-- -----------------------------------------------------------------------------
-- Q3 — Segmentation customer par valeur (RFM simplifié)
-- Recency, Frequency, Monetary
-- -----------------------------------------------------------------------------
WITH rfm AS (
    SELECT
        customer_sk,
        dateDiff('day', max(toDate(date_id)), today())  AS recency_days,
        sum(1)                                          AS frequency,
        sum(amount_eur)                                 AS monetary_eur
    FROM fact_transaction
    WHERE created_at >= today() - 180
      AND status = 'succeeded'
    GROUP BY customer_sk
)
SELECT
    CASE
        WHEN recency_days <= 30 AND frequency >= 10 AND monetary_eur >= 1000 THEN 'VIP'
        WHEN recency_days <= 60 AND frequency >= 3                            THEN 'Regular'
        WHEN recency_days <= 90                                               THEN 'Occasional'
        ELSE 'Churn_risk'
    END                                   AS segment,
    count()                               AS customer_count,
    round(avg(monetary_eur), 2)           AS avg_monetary,
    round(avg(frequency), 1)              AS avg_frequency,
    round(avg(recency_days), 1)           AS avg_recency_days
FROM rfm
GROUP BY segment
ORDER BY customer_count DESC;


-- -----------------------------------------------------------------------------
-- Q4 — Fraud trend horaire (utilise mv_hourly_fraud)
-- -----------------------------------------------------------------------------
SELECT
    toStartOfHour(hour_ts)           AS hour,
    country_code,
    payment_type,
    SUM(total_count)                 AS total,
    SUM(high_risk_count)             AS high_risk,
    ROUND(SUM(high_risk_count) / SUM(total_count) * 100, 2) AS high_risk_pct
FROM fact_hourly_fraud
WHERE hour_ts >= now() - INTERVAL 24 HOUR
GROUP BY hour, country_code, payment_type
HAVING total >= 10
ORDER BY hour DESC, high_risk_pct DESC
LIMIT 100;


-- -----------------------------------------------------------------------------
-- Q5 — Comparatif revenue YoY (Year-over-Year)
-- -----------------------------------------------------------------------------
SELECT
    toMonth(toDate(date_id))          AS month,
    toYear(toDate(date_id))           AS year,
    ROUND(SUM(gross_revenue_eur), 2)  AS revenue_eur,
    SUM(transaction_count)            AS tx_count
FROM fact_daily_revenue
WHERE toYear(toDate(date_id)) IN (2025, 2026)
GROUP BY year, month
ORDER BY month, year;


-- -----------------------------------------------------------------------------
-- Q6 — Heatmap performance par (pays merchant × devise)
-- -----------------------------------------------------------------------------
SELECT
    country_code,
    currency_code,
    SUM(transaction_count)                AS tx_count,
    ROUND(SUM(gross_revenue_eur), 2)      AS revenue_eur,
    ROUND(AVG(success_rate) * 100, 2)     AS avg_success_pct,
    ROUND(AVG(avg_fraud_score), 3)        AS avg_fraud
FROM fact_daily_revenue
WHERE toDate(date_id) >= today() - 30
GROUP BY country_code, currency_code
ORDER BY revenue_eur DESC;


-- -----------------------------------------------------------------------------
-- Q7 — Cohort analysis : rétention des customers par mois d'acquisition
-- -----------------------------------------------------------------------------
WITH first_tx AS (
    SELECT
        customer_sk,
        toStartOfMonth(toDate(min(date_id))) AS cohort_month
    FROM fact_transaction
    WHERE status = 'succeeded'
    GROUP BY customer_sk
),
activity AS (
    SELECT
        f.customer_sk,
        ft.cohort_month,
        toStartOfMonth(toDate(f.date_id)) AS activity_month
    FROM fact_transaction f
        JOIN first_tx ft USING (customer_sk)
    WHERE f.status = 'succeeded'
    GROUP BY f.customer_sk, ft.cohort_month, activity_month
)
SELECT
    cohort_month,
    dateDiff('month', cohort_month, activity_month) AS month_number,
    count(DISTINCT customer_sk)                     AS active_customers
FROM activity
WHERE cohort_month >= today() - INTERVAL 6 MONTH
GROUP BY cohort_month, month_number
ORDER BY cohort_month, month_number;
