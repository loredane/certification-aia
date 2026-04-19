-- =============================================================================
-- Question business : Revue PCI-DSS Req 10.6 — qui a fait quoi sur les
-- donnees sensibles (core.customers, core.payment_methods) au cours des
-- 7 derniers jours, en se concentrant sur les actions privilegiees ?
-- =============================================================================

SELECT
    a.event_time,
    a.actor_type,
    a.actor_id,
    a.action,
    a.resource_type,
    a.resource_id,
    a.ip_address,
    a.success,
    a.metadata->>'reason'        AS reason,
    a.metadata->>'approved_by'   AS approved_by
FROM audit.audit_log a
WHERE a.event_time >= NOW() - INTERVAL '7 days'
  AND a.resource_type IN ('core.customers', 'core.payment_methods', 'core.transactions')
  AND a.action IN ('DELETE', 'UPDATE', 'EXPORT', 'LOGIN_ADMIN', 'GRANT', 'REVOKE')
ORDER BY a.event_time DESC
LIMIT 500;

-- Agregation complementaire : nombre d'actions privilegiees par utilisateur
SELECT
    actor_id,
    action,
    COUNT(*)                                  AS n_events,
    SUM(CASE WHEN success THEN 0 ELSE 1 END)  AS n_failures,
    MAX(event_time)                           AS last_seen
FROM audit.audit_log
WHERE event_time >= NOW() - INTERVAL '7 days'
  AND action IN ('DELETE', 'UPDATE', 'EXPORT', 'GRANT', 'REVOKE')
GROUP BY actor_id, action
ORDER BY n_events DESC;
