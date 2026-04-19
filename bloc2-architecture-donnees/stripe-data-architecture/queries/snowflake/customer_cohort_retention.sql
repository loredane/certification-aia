-- =============================================================================
-- Question business : Retention par cohorte mensuelle de signup :
-- quelle part des clients inscrits en mois M effectuent au moins 1 tx
-- en M+1, M+3, M+6 ?
-- (Cas d'usage : analyse cohortes pour product / growth team)
-- =============================================================================

USE WAREHOUSE REPORTING;
USE DATABASE STRIPE_ANALYTICS;
USE SCHEMA MARTS;

WITH customer_cohort AS (
    SELECT
        customer_sk,
        DATE_TRUNC('month', customer_since) AS cohort_month
    FROM dim_customer
    WHERE customer_since >= DATEADD('month', -12, CURRENT_DATE)
),
activity AS (
    SELECT
        f.customer_sk,
        DATE_TRUNC('month', f.transaction_date) AS tx_month
    FROM fact_transaction f
    WHERE f.status = 'captured'
    GROUP BY f.customer_sk, DATE_TRUNC('month', f.transaction_date)
),
joined AS (
    SELECT
        c.cohort_month,
        DATEDIFF('month', c.cohort_month, a.tx_month) AS month_offset,
        c.customer_sk
    FROM customer_cohort c
    JOIN activity a ON c.customer_sk = a.customer_sk
    WHERE a.tx_month >= c.cohort_month
)
SELECT
    cohort_month,
    COUNT(DISTINCT customer_sk)                                             AS cohort_size,
    COUNT(DISTINCT CASE WHEN month_offset = 1 THEN customer_sk END)         AS active_m1,
    COUNT(DISTINCT CASE WHEN month_offset = 3 THEN customer_sk END)         AS active_m3,
    COUNT(DISTINCT CASE WHEN month_offset = 6 THEN customer_sk END)         AS active_m6,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN month_offset = 1 THEN customer_sk END)
          / NULLIF(COUNT(DISTINCT customer_sk), 0), 2)                      AS retention_m1_pct,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN month_offset = 3 THEN customer_sk END)
          / NULLIF(COUNT(DISTINCT customer_sk), 0), 2)                      AS retention_m3_pct,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN month_offset = 6 THEN customer_sk END)
          / NULLIF(COUNT(DISTINCT customer_sk), 0), 2)                      AS retention_m6_pct
FROM joined
GROUP BY cohort_month
ORDER BY cohort_month;
