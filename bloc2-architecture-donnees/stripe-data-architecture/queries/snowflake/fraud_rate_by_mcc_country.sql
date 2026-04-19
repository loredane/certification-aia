-- =============================================================================
-- Question business : Cartographie du taux de fraude par categorie de
-- merchant (MCC) x pays du client sur 60 jours. Utilise pour ajuster les
-- seuils de scoring par segment dans le ML service.
-- =============================================================================

USE WAREHOUSE REPORTING;
USE DATABASE STRIPE_ANALYTICS;
USE SCHEMA MARTS;

SELECT
    m.mcc_category,
    c.country_code                                  AS customer_country,
    c.region                                        AS customer_region,
    COUNT(*)                                        AS total_tx,
    SUM(f.is_high_fraud_risk)                       AS high_risk_tx,
    ROUND(100.0 * SUM(f.is_high_fraud_risk) / NULLIF(COUNT(*), 0), 2) AS fraud_rate_pct,
    ROUND(AVG(f.fraud_score), 3)                    AS avg_fraud_score,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY f.fraud_score), 3) AS p95_fraud_score,
    SUM(f.amount_usd)                               AS total_volume_usd,
    SUM(CASE WHEN f.is_high_fraud_risk = 1 THEN f.amount_usd ELSE 0 END) AS at_risk_volume_usd
FROM fact_transaction f
LEFT JOIN dim_customer c ON f.customer_sk = c.customer_sk
LEFT JOIN dim_merchant m ON f.merchant_sk = m.merchant_sk
WHERE f.transaction_date >= DATEADD('day', -60, CURRENT_DATE)
GROUP BY m.mcc_category, c.country_code, c.region
HAVING COUNT(*) >= 30
ORDER BY fraud_rate_pct DESC, total_volume_usd DESC
LIMIT 100;
