-- =============================================================================
-- Question business : Quel est le revenu net USD par region du monde
-- sur les 30 derniers jours, avec taux de succes et panier moyen ?
-- (Cas d'usage : dashboard executif hebdomadaire)
--
-- Livrable Bloc 2 AIA — demonstration d'une requete analytique OLAP
-- sur star schema Kimball (fact_transaction x dim_merchant).
-- =============================================================================

USE WAREHOUSE REPORTING;
USE DATABASE STRIPE_ANALYTICS;
USE SCHEMA MARTS;

SELECT
    m.region,
    m.country_code,
    COUNT(DISTINCT f.transaction_sk)               AS transactions,
    COUNT(DISTINCT f.customer_sk)                  AS unique_customers,
    SUM(f.revenue_usd)                             AS net_revenue_usd,
    AVG(f.amount_usd)                              AS avg_ticket_usd,
    ROUND(
        SUM(CASE WHEN f.status = 'captured' THEN 1 ELSE 0 END)::FLOAT
        / NULLIF(COUNT(*), 0) * 100, 2
    )                                              AS success_rate_pct,
    SUM(f.is_high_fraud_risk)                      AS high_risk_tx_count
FROM fact_transaction f
LEFT JOIN dim_merchant m ON f.merchant_sk = m.merchant_sk
WHERE f.transaction_date >= DATEADD('day', -30, CURRENT_DATE)
GROUP BY m.region, m.country_code
ORDER BY net_revenue_usd DESC NULLS LAST;
