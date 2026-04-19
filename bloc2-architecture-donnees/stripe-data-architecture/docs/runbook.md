# Runbook opérationnel — Stripe Data Platform

> **FIX v3-mediums #25** — Promis par `docs/SPECIFICATIONS.md` §5.4 (Run & Monitoring).
>
> Ce document contient les procedures d'intervention pour les incidents
> courants. **Les contacts on-call sont fictifs** (cas d'etude RNCP).

---

## 1. Contacts on-call (fictifs)

| Role | Nom | Email | Telephone | Astreinte |
|---|---|---|---|---|
| Data Platform L1 | Equipe Paris | `data-oncall@stripe-demo.local` | +33 1 55 55 01 00 | 24/7 |
| Data Platform L2 (Airflow, dbt, Snowflake) | *M. Thomas Leroy* | `thomas.leroy@stripe-demo.local` | +33 6 55 55 01 01 | heures ouvrables |
| ML Engineering | *Mme Sophie Chen* | `ml-oncall@stripe-demo.local` | +33 6 55 55 01 02 | 24/7 |
| CISO (securite) | *M. Julien Rousseau* | `ciso@stripe-demo.local` | +1 415 555 0199 | 24/7 |
| DPO (RGPD) | *Mme Camille Bernard* | `dpo@stripe-demo.local` | +353 1 555 0100 | heures ouvrables |

Escalade : L1 -> L2 apres 30 min sans resolution -> CISO si security impact.

---

## 2. Incidents frequents

### 2.1. MinIO down

**Symptomes** :
- DAG `ingest_to_snowflake` echoue sur `sync_postgres_to_s3` avec `ConnectionError`.
- Grafana : panel "MinIO health" rouge.
- Healthcheck Docker : `stripe_minio` en `unhealthy`.

**Diagnostic** :
```bash
docker ps --filter name=stripe_minio
docker inspect stripe_minio --format '{{.State.Health.Status}}'
docker logs --tail=200 stripe_minio
curl -fsS http://localhost:9000/minio/health/live
```

**Actions** :
1. Si healthcheck KO : `docker compose restart minio minio-init`
2. Si volume `minio_data` corrompu :
   ```bash
   docker compose down minio
   docker volume inspect stripe-data-architecture-v3_minio_data
   # backup si possible, sinon recreation :
   docker volume rm stripe-data-architecture-v3_minio_data
   docker compose up -d minio minio-init
   ```
3. Re-trigger du DAG `ingest_to_snowflake` depuis Airflow UI.

**Escalade** : L2 si le volume est perdu, CISO si suspicion d'intrusion.

---

### 2.2. Snowflake freshness KO

**Symptomes** :
- Task `check_snowflake_freshness` du DAG `ingest_to_snowflake` echoue avec
  `ERROR : freshness > 6h on raw_stripe.TRANSACTIONS`.
- Grafana : data_age metric rouge.

**Diagnostic** :
```sql
-- Sur Snowflake
SELECT MAX(_AIRBYTE_LOADED_AT) AS last_load
FROM RAW.STRIPE.TRANSACTIONS;

-- Comparer avec OLTP
SELECT MAX(created_at) FROM core.transactions;
```

Verifier dans Airbyte UI le statut du dernier sync de la connection
`postgres -> snowflake`.

**Actions** :
1. **Si Airbyte est UP mais le dernier sync a echoue** :
   - Consulter les logs Airbyte (`abctl local logs` ou UI).
   - Re-trigger le sync depuis Airbyte UI ou via le DAG :
     Airflow UI -> `ingest_to_snowflake` -> Trigger DAG.
2. **Si le sync est bloque (CDC replication slot plein)** :
   ```sql
   -- Sur postgres
   SELECT slot_name, active, restart_lsn
   FROM pg_replication_slots;
   ```
   Si `active = false` depuis longtemps, relancer le sync full-refresh
   depuis Airbyte.
3. **Si Snowflake warehouse suspendu** : verifier dans Snowsight que
   `LOADING` et `TRANSFORMING` ont `AUTO_RESUME = TRUE`.

**Escalade** : L2 si replication slot corrompu. DPO si retard > 24h (impact
potentiel sur exercice de droits RGPD).

---

### 2.3. ml-service 5xx

**Symptomes** :
- `transaction-generator` : `tx=... ML call failed: 500`.
- Grafana : `fraud_score_requests_total` en chute, `auth_failures` en hausse.
- Prometheus alert `ml_service_error_rate > 5%`.

**Diagnostic** :
```bash
docker logs --tail=200 stripe_ml_service
curl -fsS http://localhost:8001/health
```

Cas frequents :
- `MONGO_URI is not set` -> env var manquante au lancement.
- `Failed to load model at /app/models/fraud_model.pkl` -> pickle absent
  (le DAG `ml_fraud_scoring` n'a pas encore tourne) -> le service tombe
  en fallback rule-based, mais c'est attendu.
- `ServerSelectionTimeoutError` -> mongo down ou reseau docker casse.

**Actions** :
1. Si mongo down : cf. §2.4.
2. Si pickle corrompu :
   ```bash
   docker volume rm stripe-data-architecture-v3_ml_models
   docker compose up -d ml-service
   # Puis re-trigger le DAG ml_fraud_scoring
   ```
3. Si auth_failures en hausse : revoir `ML_API_KEYS` dans `.env`
   et rotation des cles compromises.

**Escalade** : ML Engineering L2 si AUC drift > 10% constate par le DAG
`monitor_drift`.

---

### 2.4. MongoDB down

**Symptomes** :
- `ml-service` 5xx massif.
- Task `compute_features` du DAG `ml_fraud_scoring` echoue.
- mongo-express (http://127.0.0.1:8081) inaccessible.

**Diagnostic** :
```bash
docker logs --tail=200 stripe_mongo
docker exec stripe_mongo mongosh --eval 'db.runCommand({ping:1})'
```

**Actions** :
1. Restart : `docker compose restart mongo`.
2. Si le `init-mongo.sh` a echoue (MONGO_APP_PASSWORD absent) : corriger
   `.env` puis `docker compose down mongo && docker volume rm
   stripe-data-architecture-v3_mongo_data && docker compose up -d mongo`.
3. Si fichier WT (WiredTiger) corrompu : restore depuis backup
   (non couvert par la demo locale, documente pour la prod).

---

### 2.5. Airflow scheduler bloque

**Symptomes** :
- Aucun DAG run ne demarre depuis > 15 min alors que des schedules sont dus.
- Airflow UI : `/health` retourne `scheduler: unhealthy`.

**Actions** :
```bash
docker compose restart airflow-scheduler
docker logs --tail=100 stripe_airflow_scheduler
```
Si base metadata corrompue : `docker compose restart airflow-init` puis
scheduler + webserver.

---

## 3. Procedures regulieres

| Frequence | Action | Owner |
|---|---|---|
| Quotidien | Revue alerts Grafana + Prometheus | L1 |
| Hebdomadaire | Revue dbt test results + freshness | Analytics Eng |
| Mensuel | Rotation des API keys ML + grafana + mongo-express | CISO |
| Trimestriel | Revue RBAC Snowflake + policies MinIO | CISO + Data Eng |
| Annuel | Rotation cles KMS + audit PCI-DSS | CISO |

---

## 4. Evenements exceptionnels

### Data breach (GDPR Art. 33)

1. L1/L2 alerte CISO + DPO dans l'heure.
2. Isolation du composant compromis (stop docker container ou flag
   read-only sur le bucket S3).
3. Collecte logs immuables (`audit.audit_log` + Cloudtrail en prod).
4. Notification DPC Irlande sous 72h (DPO).
5. Post-mortem + AIPD mise a jour.

### Suspicion d'exfiltration

1. Isoler le compte technique suspect (revoke role Snowflake, disable
   service account MinIO).
2. Forensic : `audit.audit_log` + logs Airbyte + logs applicatifs.
3. CISO + DPO informes immediatement.
