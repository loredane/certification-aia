-- =============================================================================
-- Question business : Quels sont les 20 merchants avec le plus fort taux de
-- fraude (>= 5% de transactions high-risk) sur les 90 derniers jours,
-- avec volume financier a risque ?
-- (Cas d'usage : revue mensuelle risk team, candidates au gel de compte)
-- =============================================================================

USE WAREHOUSE REPORTING;
USE DATABASE STRIPE_ANALYTICS;
USE SCHEMA MARTS;

WITH agg AS (
    SELECT
        m.merchant_sk,
        m.business_name,
        m.country_code,
        m.mcc_category,
        COUNT(*)                         AS total_tx,
        SUM(f.is_high_fraud_risk)        AS high_risk_tx,
        SUM(f.amount_usd)                AS total_volume_usd,
        SUM(CASE WHEN f.is_high_fraud_risk = 1 THEN f.amount_usd ELSE 0 END) AS at_risk_volume_usd,
        AVG(f.fraud_score)               AS avg_fraud_score
    FROM fact_transaction f
    LEFT JOIN dim_merchant m ON f.merchant_sk = m.merchant_sk
    WHERE f.transaction_date >= DATEADD('day', -90, CURRENT_DATE)
    GROUP BY m.merchant_sk, m.business_name, m.country_code, m.mcc_category
    HAVING COUNT(*) >= 50  -- seuil statistique
)
SELECT
    business_name,
    country_code,
    mcc_category,
    total_tx,
    high_risk_tx,
    ROUND(high_risk_tx::FLOAT / NULLIF(total_tx, 0) * 100, 2) AS fraud_rate_pct,
    ROUND(avg_fraud_score, 3)             AS avg_fraud_score,
    ROUND(at_risk_volume_usd, 2)          AS at_risk_volume_usd,
    ROUND(total_volume_usd, 2)            AS total_volume_usd
FROM agg
WHERE high_risk_tx::FLOAT / NULLIF(total_tx, 0) >= 0.05
ORDER BY at_risk_volume_usd DESC
LIMIT 20;
