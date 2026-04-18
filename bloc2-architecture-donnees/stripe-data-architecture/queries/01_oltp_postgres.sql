-- =============================================================================
-- Livrable 8 — Requêtes SQL sur OLTP PostgreSQL
-- Cas business : transactions en direct, remboursements, disputes, audit
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Q1 — Transactions d'un merchant aujourd'hui, avec détail client + PM
-- Utilise les index idx_tx_merchant, idx_pm_customer, idx_customer_country
-- -----------------------------------------------------------------------------
SELECT
    t.transaction_id,
    t.created_at,
    t.amount_minor / 100.0       AS amount,
    t.currency_code,
    t.status,
    t.fraud_score,
    c.email,
    c.country_code               AS customer_country,
    pmt.type_code                AS payment_type,
    pm.brand,
    pm.last4
FROM core.transaction t
    JOIN core.customer c         USING (customer_id)
    JOIN core.payment_method pm  USING (payment_method_id)
    JOIN reference.payment_method_type pmt USING (payment_method_type_id)
WHERE t.merchant_id = '<MERCHANT_UUID>'::uuid
  AND t.created_at >= CURRENT_DATE
ORDER BY t.created_at DESC
LIMIT 100;


-- -----------------------------------------------------------------------------
-- Q2 — Top 10 customers par volume des 30 derniers jours
-- -----------------------------------------------------------------------------
SELECT
    c.customer_id,
    c.email,
    c.country_code,
    COUNT(t.*)                                   AS tx_count,
    SUM(t.amount_minor) / 100.0                  AS total_amount,
    AVG(t.amount_minor) / 100.0                  AS avg_amount,
    COUNT(t.*) FILTER (WHERE t.status = 'failed') AS failed_count
FROM core.customer c
    JOIN core.transaction t USING (customer_id)
WHERE t.created_at >= NOW() - INTERVAL '30 days'
  AND c.is_deleted = FALSE
GROUP BY c.customer_id, c.email, c.country_code
HAVING COUNT(t.*) > 5
ORDER BY total_amount DESC
LIMIT 10;


-- -----------------------------------------------------------------------------
-- Q3 — Transactions à haut risque non traitées (fraud review queue)
-- Utilise l'index partiel idx_tx_fraud
-- -----------------------------------------------------------------------------
SELECT
    t.transaction_id,
    t.created_at,
    t.amount_minor / 100.0  AS amount,
    t.currency_code,
    t.fraud_score,
    t.fraud_decision,
    c.email,
    c.country_code          AS customer_country,
    m.country_code          AS merchant_country,
    CASE WHEN c.country_code != m.country_code THEN 'CROSS_BORDER' ELSE 'DOMESTIC' END AS pattern
FROM core.transaction t
    JOIN core.customer c USING (customer_id)
    JOIN core.merchant m USING (merchant_id)
WHERE t.fraud_score > 0.7
  AND t.fraud_decision = 'review'
  AND t.created_at >= NOW() - INTERVAL '24 hours'
ORDER BY t.fraud_score DESC, t.created_at DESC;


-- -----------------------------------------------------------------------------
-- Q4 — Disputes ouvertes avec évidence due dans 48h
-- -----------------------------------------------------------------------------
SELECT
    d.dispute_id,
    d.transaction_id,
    d.reason_code,
    d.evidence_due,
    EXTRACT(EPOCH FROM (d.evidence_due - CURRENT_DATE)) / 3600 AS hours_remaining,
    t.amount_minor / 100.0 AS amount,
    t.currency_code,
    m.business_name        AS merchant
FROM core.dispute d
    JOIN core.transaction t USING (transaction_id)
    JOIN core.merchant m    USING (merchant_id)
WHERE d.status = 'open'
  AND d.evidence_due <= CURRENT_DATE + INTERVAL '2 days'
ORDER BY d.evidence_due ASC;


-- -----------------------------------------------------------------------------
-- Q5 — Audit trail : qui a modifié quelles transactions (compliance PCI-DSS req.10)
-- -----------------------------------------------------------------------------
SELECT
    a.event_time,
    a.db_user,
    a.action,
    a.row_pk,
    a.client_ip,
    jsonb_pretty(a.old_values) AS before,
    jsonb_pretty(a.new_values) AS after
FROM audit.access_log a
WHERE a.table_name = 'core.transaction'
  AND a.event_time >= NOW() - INTERVAL '7 days'
  AND a.action IN ('UPDATE', 'DELETE')
ORDER BY a.event_time DESC
LIMIT 100;


-- -----------------------------------------------------------------------------
-- Q6 — Taux de succès par méthode de paiement (7 derniers jours)
-- -----------------------------------------------------------------------------
SELECT
    pmt.type_code                                                AS payment_type,
    pm.brand,
    COUNT(t.*)                                                   AS total_tx,
    COUNT(t.*) FILTER (WHERE t.status = 'succeeded')             AS succeeded,
    COUNT(t.*) FILTER (WHERE t.status = 'failed')                AS failed,
    ROUND(100.0 * COUNT(t.*) FILTER (WHERE t.status = 'succeeded')
          / COUNT(t.*), 2)                                       AS success_rate_pct
FROM core.transaction t
    JOIN core.payment_method pm  USING (payment_method_id)
    JOIN reference.payment_method_type pmt USING (payment_method_type_id)
WHERE t.created_at >= NOW() - INTERVAL '7 days'
GROUP BY pmt.type_code, pm.brand
HAVING COUNT(t.*) >= 10
ORDER BY success_rate_pct DESC;
