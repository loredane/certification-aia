# Cahier des charges — Stripe Data Architecture

> **Compétence RNCP visée** : *Élaborer un cahier des charges d'architecture de données intégrant contraintes techniques et normes en vigueur*

## 1. Contexte métier

**Stripe Inc.** — FinTech fondée en 2010 à San Francisco, traite des milliards de transactions par an pour des millions de marchands dans 135+ pays. Produits : paiements en ligne, souscriptions, marketplaces, lutte anti-fraude.

## 2. Problématiques identifiées

| Problématique | Cause | Impact |
|---|---|---|
| Workloads transactionnels complexes | Diversité instruments (carte, SEPA, wallets) × devises × pays | Latence, intégrité |
| Besoins analytiques avancés | Équipes BI, Data Science, Finance, Risk | Time-to-insight |
| Données non structurées massives | Logs app, clickstream, feedbacks clients, features ML | Stockage, requêtage |
| Intégration inter-systèmes | Dispersion SGBDR, entrepôts, buckets S3 | Cohérence, silo |
| Conformité réglementaire | GDPR, PCI-DSS, CCPA | Risque légal, amendes |

## 3. Contraintes techniques

### 3.1. Performance

| Axe | SLA |
|---|---|
| OLTP — écriture transaction | P99 < 50 ms |
| OLTP — lecture profil client | P99 < 20 ms |
| OLAP — agrégation 30 jours | P95 < 5 s |
| ML fraud scoring | P99 < 200 ms end-to-end |
| Batch pipeline freshness | ≤ 1 h |

### 3.2. Volume

- ~10 milliards de transactions / an → ~300 TB en fact table (avec compression)
- ~100 milliards d'événements clickstream / an (MongoDB, rétention 90 j)
- 500 000+ marchands actifs, ~200 millions de clients

### 3.3. Disponibilité

| Service | SLA |
|---|---|
| API paiement (OLTP) | 99.995 % (≤ 26 min downtime/an) |
| Data Warehouse (OLAP) | 99.9 % |
| Pipelines batch | 99.5 % |

### 3.4. Scalabilité

- OLTP : horizontal via sharding par `merchant_id` (prévu phase 2)
- OLAP : Snowflake auto-scale (warehouse size élastique)
- NoSQL : MongoDB sharded cluster (shard key = `customer_id`)
- Streaming : Kafka partitioning (12 partitions sur topic transactions)

## 4. Contraintes normatives

### 4.1. GDPR (Règlement européen 2016/679)

| Exigence | Implémentation |
|---|---|
| Consentement | Champs tracés dans `core.customers` + audit log |
| Droit d'accès | Endpoint API export JSON de toutes les données d'un `customer_id` |
| Droit à l'effacement | Soft delete (`deleted_at`) + DAG Airflow de purge propagée OLAP + NoSQL sous 72h |
| Portabilité | Export au format Parquet standardisé |
| Pseudonymisation | `email_hash` SHA-256 stocké en plus du plain email (retrait pour analytics) |
| Minimisation | CCN jamais stocké (tokenization via Vault), seulement last4 + brand |
| Data Protection Officer | Contact défini dans `docs/` |

### 4.2. PCI-DSS v4.0

| Requirement | Implémentation |
|---|---|
| Req 3.2 — pas de stockage CCN | Tokenization, seul last4 stocké |
| Req 3.4 — chiffrement at-rest | AES-256 (PostgreSQL `pgcrypto`, S3 SSE-KMS, Snowflake customer-managed keys) |
| Req 4.1 — chiffrement in-transit | TLS 1.3 obligatoire tous services |
| Req 7 — least privilege | RBAC Snowflake (`LOADER_ROLE`, `TRANSFORM_ROLE`, `ANALYST_ROLE`), RLS PostgreSQL |
| Req 8 — authentification forte | MFA, rotation clés KMS annuelle |
| Req 10 — audit logging | `audit.audit_log` append-only, rétention 7 ans sur S3 Glacier |
| Req 10.6 — revue logs | SIEM (Splunk / OpenSearch en prod) |

### 4.3. CCPA (Californie)

- Opt-out "Do Not Sell" : flag dans `core.customers` + respecté par tous les ML models
- Disclosure annuelle : rapport généré via dbt mart

## 5. Plan sécurité

### 5.1. Chiffrement

- **At rest** : AES-256 sur tous les volumes (postgres, mongo, minio, snowflake)
- **In transit** : TLS 1.3 obligatoire, certificats renouvelés auto via ACM
- **Champs sensibles** : colonne `phone_encrypted` en `BYTEA` chiffré avec `pgcrypto`
- **Clés** : AWS KMS avec key rotation annuelle activée

### 5.2. Contrôle d'accès

- **RBAC Snowflake** : 4 rôles (LOADER, TRANSFORM, ANALYST, DATA_ENG)
- **PostgreSQL** : rôles applicatifs distincts, RLS sur tables sensibles
- **MongoDB** : user `stripe_app` avec `readWrite` sur `stripe_nosql` uniquement
- **IAM AWS** : policies avec principle of least privilege, service accounts dédiés
- **Secrets** : AWS Secrets Manager / HashiCorp Vault (jamais en clair dans le code)

### 5.3. Audit

- `audit.audit_log` PostgreSQL — toute action sensible loggée, UPDATE/DELETE révoqués
- CloudTrail AWS pour toute action sur S3, KMS, RDS
- Snowflake Access History automatique (retained 365 jours)
- Archivage 7 ans sur S3 Glacier

### 5.4. Réponse à incident

- Runbook dans `docs/` (à rédiger séparément)
- SLA notification breach GDPR : 72h max
- Point de contact DPO + CISO

## 6. Livrables attendus

Voir `README.md` et le mapping RNCP.

## 7. Choix technologiques et justifications

| Choix | Alternative considérée | Justification |
|---|---|---|
| **PostgreSQL** pour OLTP | MySQL, Oracle | Open-source, ACID complet, extensions (uuid, pgcrypto, logical replication) |
| **Snowflake** pour DWH | BigQuery, Redshift, ClickHouse | Enseigné dans cursus Jedha, séparation compute/storage, ELT natif |
| **MongoDB** pour NoSQL | Cassandra, DynamoDB | Schema flexible, indexation riche, $jsonSchema validation |
| **Airbyte** pour ELT | Fivetran, Stitch | Open-source, enseigné dans cursus Jedha, 350+ connecteurs |
| **Airflow** pour orchestration | Dagster, Prefect | Maturité, adoption industrielle, enseigné dans cursus Jedha |
| **dbt** pour transform | SQL stored procs, Dataform | Standard industrie, tests intégrés, docs auto |
| **Kafka** pour streaming | Kinesis, RabbitMQ | Throughput, persistance configurable, CDC natif |
| **FastAPI** pour ML service | Flask, Django | Async natif, validation Pydantic, OpenAPI auto |
| **Prometheus + Grafana** | Datadog, New Relic | Open-source, flexibilité, prix |
| **MinIO** (local) / **S3** (prod) | Blob Storage, GCS | S3-compatible API, portable local ↔ cloud |

## 8. Trajectoire future

- Phase 2 : Sharding PostgreSQL par `merchant_id`
- Phase 3 : Feature store managé (Feast / Tecton)
- Phase 4 : Real-time OLAP (Druid / Pinot) pour dashboards <1s
- Phase 5 : ML inference sur GPU (Triton) pour modèles deep learning
