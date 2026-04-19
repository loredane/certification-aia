# Architecture technique — Stripe Data Platform

## 1. Vue d'ensemble

Architecture hybride **OLTP + OLAP + NoSQL** unifiée pour traiter :
- Des milliards de transactions financières (ACID, intégrité garantie)
- De l'analytique historique massive (agrégations, BI, data science)
- Des données non structurées à très gros volume (logs, clickstream, features ML)
- De la détection de fraude temps réel (< 200 ms de bout en bout)
- La conformité réglementaire stricte (GDPR, PCI-DSS, CCPA)

## 2. Couches de l'architecture

### 2.1. Couche OLTP — PostgreSQL 16

- **Rôle** : source de vérité transactionnelle, ACID, intégrité référentielle
- **Schéma** : 3NF normalisé (voir `docker/postgres/init.sql`)
- **Entités principales** : `core.customers`, `core.merchants`, `core.payment_methods`, `core.transactions`, `core.refunds`, `core.disputes`
- **Référentiels** : `reference.countries`, `reference.currencies`, `reference.exchange_rates`, `reference.mcc_codes`
- **Audit** : `audit.audit_log` immutable (DELETE/UPDATE révoqués)
- **Indexation stratégique** :
  - Btree sur clés étrangères (jointures)
  - BRIN sur `created_at` (time-series, 10× plus compact)
  - Index partiels sur status rares (pending, failed)
- **Haute dispo** : logical replication (WAL) pour Airbyte CDC + réplicas read-only en prod
- **Référence DAMA** : ch. 5 §1.3.3 (Relational Modeling), ch. 6 §1.3.2 (OLTP)

### 2.2. Couche Data Lake — S3 / MinIO

- **Rôle** : staging intermédiaire, rétention longue, replay
- **Architecture Medallion** :
  - **Bronze** (`stripe-raw`) : données brutes telles quelles
  - **Silver** (`stripe-staging`) : nettoyées, typées, dédupliquées
  - **Gold** (`stripe-marts`) : business-ready
- **Format** : Parquet (columnar, compression snappy) pour analytique
- **En local** : MinIO (S3-compatible) dans Docker
- **En prod** : AWS S3 avec SSE-KMS encryption, versioning, lifecycle Glacier → Deep Archive (rétention 7 ans PCI-DSS)
- **Référence** : Fundamentals of Data Engineering ch. 8 (Lakehouse / Medallion)

### 2.3. Couche OLAP — Snowflake Data Warehouse

- **Rôle** : analytique historique, BI, star schema Kimball
- **Organisation** :
  - Base `RAW` (chargée par Airbyte)
  - Base `STRIPE_ANALYTICS` schémas `STAGING` + `MARTS` + `REPORTS`
- **Warehouses séparés** (séparation des coûts) :
  - `LOADING` (XS) — ingestion Airbyte
  - `TRANSFORMING` (S) — dbt runs
  - `REPORTING` (S) — dashboards BI
- **Star schema** (voir `dbt/stripe_analytics/models/marts/`) :
  - Fact : `fact_transaction` (grain = 1 transaction, incrémental, clustering par `transaction_date`)
  - Dimensions : `dim_customer`, `dim_merchant`, `dim_date`
  - Marts métier : `mart_revenue_daily`, `mart_fraud_analysis`
- **Performance** : clustering keys, query result caching, materialized views
- **Référence DAMA** : ch. 5 §1.3.4 (Dimensional Modeling), ch. 6 §1.3.4 (Data Warehousing)

### 2.4. Couche NoSQL — MongoDB 7

- **Rôle** : données non structurées, feature store ML, logs applicatifs
- **Collections** :
  - `clickstream_events` — événements web (TTL 90 jours)
  - `ml_features_customer` / `ml_features_merchant` — feature store online
  - `fraud_alerts` — résultats scoring fraud (rétention 30 jours)
  - `customer_feedback` — avis libres, analyse de sentiment
  - `app_logs` — logs techniques (TTL 30 jours)
- **Patterns** :
  - **Embedding** pour données cohésives (features groupées par `customer_id`)
  - **Referencing** pour relations many-to-many
  - **Indexation** composite sur clés d'accès (`customer_id + timestamp DESC`)
  - **TTL indexes** pour rétention automatique
- **Schema validation** : `$jsonSchema` sur `clickstream_events`, `ml_features_customer`, `fraud_alerts`
- **Référence DAMA** : ch. 5 §2.1.5 (NoSQL Modeling), ch. 6 §1.3.8 (Document stores)

### 2.5. Couche streaming — Kafka

- **Rôle** : event bus temps réel pour fraud detection et clickstream
- **Topics** (voir `kafka/topics-init.sh`) :
  - `cdc.transactions`, `cdc.customers` — topics provisionnés pour un futur
    connecteur Debezium/Kafka Connect (actuellement **non câblé** ;
    le pipeline de production utilise Airbyte batch hourly — voir §2.6)
  - `events.clickstream` — événements web
  - `events.fraud_scored` — provisionné pour un futur producer côté ML service
    (cf. *Trajectoire future* dans SPECIFICATIONS §8)
  - `dlq.errors` — dead letter queue
- **Configuration** :
  - Partitionnement par merchant_id (scalabilité horizontale)
  - Réplication factor 3 en prod, 1 en demo
  - Compression zstd
  - Retention par topic (7j pour CDC, 30j pour fraud audit)
- **Référence DAMA** : ch. 8 §1.3.10 (Event-based integration)

### 2.6. Couche ELT — Airbyte

- **Rôle** : ingestion PostgreSQL → S3 → Snowflake
- **Connecteurs** :
  - Source PostgreSQL (CDC logical replication)
  - Destination S3 (Parquet)
  - Destination Snowflake
- **Orchestration** via Airflow API calls
- **Référence** : cursus Jedha *"ELT with Airbyte"*, DAMA ch. 8 §1.3.1 (ELT pattern)

### 2.7. Couche orchestration — Apache Airflow 2.9

- **DAGs** :
  - `ingest_to_snowflake` (@hourly) — déclenche sync Airbyte
  - `transform_dbt` (15 min après) — dbt run/test/docs sur Snowflake
  - `ml_fraud_scoring` (daily 03:00) — re-train XGBoost + canary deploy
- **Pattern** : chaque DAG est idempotent, versionné, avec SLA et retries
- **Référence** : cursus Jedha *"ETL with Airflow"*, DAMA ch. 8 §2.1 (Orchestration)

### 2.8. Couche ML — FastAPI service + MongoDB feature store

- **Rôle** : scoring fraud temps réel (P99 < 50 ms)
- **Architecture** :
  - Feature lookup : MongoDB `ml_features_customer` (clé = `customer_id`)
  - Modèle : **XGBoost** chargé dynamiquement depuis `ML_MODEL_PATH` si un
    pickle produit par le DAG `ml_fraud_scoring` est présent. Sinon,
    fallback automatique sur une **stratégie rule-based** (heuristiques
    sur amount, velocity, risk_score, country) — implémenté dans
    `score_rulebased()`.
  - Sortie : score [0,1] + décision (`approve` / `review` / `block`) + raisons
  - Persistance : MongoDB `fraud_alerts`
- **Sécurité** : authentification par header `X-API-Key` (liste CSV dans
  `ML_API_KEYS`), rate limit 120 req/min/IP (slowapi), user container
  non-root.
- **Monitoring** : Prometheus metrics (`fraud_score_requests_total`,
  `fraud_score_latency_seconds`, `fraud_score_auth_failures_total`)
- **Référence DAMA** : ch. 14 (Big Data & Data Science)

### 2.9. Couche monitoring — Prometheus + Grafana

- **Prometheus** scrape :
  - ML service (endpoint natif `/metrics` via `prometheus_client`)
  - MinIO cluster (endpoint natif `/minio/v2/metrics/cluster`)
  - Prometheus self-monitoring
  - **Note** : Kafka et Airflow nécessitent des exporters supplémentaires
    (JMX Exporter pour Kafka, `statsd_exporter` ou plugin Prometheus pour
    Airflow 2.x) — prévu en Phase 2.
- **Grafana** dashboards :
  - Pipeline overview (requests/s, latencies P50/P95/P99, decisions distribution)
  - Fraud rates par région et MCC
  - Data freshness par table (via dbt source freshness)
- **Alerting** : PagerDuty en prod pour SLA breach

## 3. Flux de données

### 3.1. Flux batch (ELT)

```
PostgreSQL OLTP
    ↓ [Airbyte — hourly, CDC]
S3 (bronze) — Parquet files
    ↓ [Airbyte — hourly]
Snowflake RAW.STRIPE
    ↓ [dbt run staging — hourly+15]
Snowflake STAGING (views)
    ↓ [dbt run marts — hourly+15]
Snowflake MARTS (fact + dims + marts)
    ↓
BI dashboards / exports
```

### 3.2. Flux streaming temps réel

```
Application (checkout) ─┬─> PostgreSQL INSERT
                        └─> ML Service /score (auth X-API-Key)
                                ↓
                        MongoDB feature lookup
                                ↓
                        Scoring : XGBoost si modèle pickle chargé,
                                   sinon règles rule-based (P99 < 50ms)
                                ↓
                        MongoDB fraud_alerts (persistance décisions)
                                ↓
                        Décision : approve | review | block
```

*Note : la publication vers Kafka `events.fraud_scored` n'est pas encore
implémentée côté service (topic provisionné pour Phase 2).*

### 3.3. Flux feature engineering

```
Snowflake fact_transaction (historique)
    ↓ [Airflow DAG ml_fraud_scoring, daily]
Feature computation (Python + pandas)
    ↓
MongoDB ml_features_customer (upsert, keyed)
    ↓
Exposé au ML service pour lookup online
```

## 4. Sécurité et conformité

Voir `docs/SPECIFICATIONS.md` section 5.

## 5. Scalabilité

- **OLTP** : read replicas + partitioning par mois sur `transactions`
- **OLAP** : Snowflake auto-scale (warehouse size dynamique selon charge)
- **NoSQL** : MongoDB sharded cluster en prod (shard key = `customer_id`)
- **Streaming** : Kafka partitionnement horizontal + consumer groups
- **ML service** : déploiement Kubernetes HPA (Horizontal Pod Autoscaler)

## 6. Références méthodologiques

- **DAMA-DMBOK2** — chapitres 4, 5, 6, 7, 8, 14
- **Fundamentals of Data Engineering** — Reis & Housley, O'Reilly 2022, ch. 3, 7, 8
- **Cursus Jedha Lead Data Science** — OLTP/OLAP modeling, ELT with Airbyte, ETL with Airflow, dbt with Snowflake
