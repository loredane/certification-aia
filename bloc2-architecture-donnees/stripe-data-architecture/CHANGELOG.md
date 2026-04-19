# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

---

## [v3-mediums] — 2026-04-19

Correction des ~28 issues de sévérité **MOYEN** et **BAS** identifiées par
l'audit du repo v2/v3 (cf. `audit_stripe_data_architecture_v2.docx`), et
ajout des livrables manquants pour le jury Bloc 2 (queries, runbook, DPO,
Makefile, CI).

### Fixed — Bugs techniques dbt / Snowflake

- **[MOY] #1 `fact_transaction.sql`** — sentinel d'incrémental `'1900-01-01'::TIMESTAMP`
  incompatible avec `_AIRBYTE_LOADED_AT` (TIMESTAMP_TZ). Remplacé par
  `TO_TIMESTAMP_TZ('1900-01-01')`.
- **[MOY] #2 `dim_date.sql`** — `EXTRACT(DAYOFWEEK ...)` dépend du paramètre
  de session `WEEK_START`. Remplacé par `DAYOFWEEKISO` (1=lundi, 7=dimanche,
  stable). `is_weekend` aligné sur `IN (6, 7)`.
- **[MOY] #3 Staging manquants** — créés `stg_refunds.sql`, `stg_disputes.sql`,
  `stg_exchange_rates.sql`. `fact_transaction` enrichie de LEFT JOIN sur
  refunds/disputes pour propager les statuts `refunded` / `disputed`
  cohérents avec `accepted_values` de `_marts.yml`.
- **[MOY] #6 `transform_dbt.py`** — `schedule="15 * * * *"` ne garantissait pas
  que `ingest_to_snowflake` soit terminé. Passé à `schedule=None` (trigger-only
  via le `TriggerDagRunOperator` du DAG amont).
- **[MOY] #7 Snowflake `01_setup_snowflake.sql`** — passwords
  `Change_Me_Airbyte_2026!` / `Change_Me_DBT_2026!` hardcodés remplacés par
  variables snowsql (`&airbyte_password`, `&dbt_password`) + directive
  `!set variable_substitution=true`.
- **[MOY] #8 Snowflake `EXCHANGE_RATES`** — ajout `CONSTRAINT PK (RATE_ID)`
  et `UQ (FROM_CURRENCY, TO_CURRENCY, EFFECTIVE_DATE)`.
- **[MOY] #9 `profiles.yml`** — `dev` et `prod` désormais distincts. `dev`
  utilise `DBT_{{ USER | upper }}` (isole chaque dev), `prod` garde
  `schema: MARTS`. Evite l'écrasement accidentel du mart prod par un
  `dbt run` local.

### Fixed — Sécurité

- **[MOY] #5 `docker/mongo/init-mongo.js`** supprimé (contenait un password
  `change_me_mongo_app` hardcodé). Remplacé par `init-mongo.sh` qui lit
  `$MONGO_APP_PASSWORD` depuis l'environnement via `mongosh --eval`.
  Ajout des variables `MONGO_APP_USER` / `MONGO_APP_PASSWORD` dans
  `.env.example` et `docker-compose.yml`.
- **[MOY] #10 `airbyte/configs/postgres_source.yaml`** — `ssl_mode: disable`
  passé à `ssl_mode.mode: require` (défaut secure). Commentaire explicite
  pour l'override DEV.
- **[MOY] #11 Airbyte `s3_destination.yaml`** — ne réutilise plus le root
  `MINIO_USER`. Le sidecar `minio-init` provisionne un service account
  dédié `$AIRBYTE_S3_ACCESS_KEY` avec policy JSON scoped à
  `stripe-raw/*` et `stripe-staging/*`. Ajout des vars correspondantes.
- **[MOY] #12 `docker-compose.yml` ports** — `postgres:5432` et `mongo:27017`
  bindés sur `127.0.0.1` (plus d'exposition LAN).
- **[MOY] #13 Hardening containers** — `security_opt: [no-new-privileges:true]`
  sur postgres, mongo, minio-init, ml-service. `read_only: true` +
  `tmpfs: /tmp` + `cap_drop: [ALL]` sur ml-service (compatible avec
  FastAPI/uvicorn + xgboost + prometheus-client).

### Fixed — Qualité code

- **[MOY] #17 `transaction-generator.py`** — `datetime.utcnow()` (déprécié
  Python 3.12+) remplacé par `datetime.now(timezone.utc)`.
- **[MOY] #20 Audit source TRANSACTIONS** — nouveau modèle dbt
  `stg_transactions_rejected` qui matérialise les tx avec `STATUS IS NULL`
  (auparavant silencieusement filtrées par `stg_transactions`). Test
  `dbt_expectations.expect_table_row_count_to_be_between` avec
  `severity: warn` au-delà de 100 lignes.

### Added — Tests dbt enrichis (#18)

- `packages.yml` : ajout de `calogica/dbt_expectations@0.10.3`.
- `_marts.yml` entièrement réécrit : 20+ tests incluant
  `expect_column_values_to_be_between` (fraud_score, risk_score,
  amount, revenue_usd, fraud_rate_pct, success_rate_pct),
  `expect_column_value_lengths_to_equal` (country_code, currency_code),
  `expect_table_row_count_to_be_between`, relations `fact_transaction.date_sk
  -> dim_date.date_sk`.

### Added — Livrables manquants pour le jury

- **#23 `queries/`** — 7 requêtes business commentées :
  - `snowflake/revenue_by_region.sql`
  - `snowflake/top_fraud_merchants.sql`
  - `snowflake/customer_cohort_retention.sql`
  - `snowflake/fraud_rate_by_mcc_country.sql`
  - `postgres/audit_log_review.sql` (revue PCI-DSS Req 10.6)
  - `mongodb/clickstream_funnel.js` (aggregation pipeline)
  - `mongodb/top_fraud_customers.js`
  + `queries/README.md` avec mapping compétences RNCP.
- **#24 `Makefile`** — cibles `up, down, restart, reset, ps, logs, seed,
  generate, dbt-deps, dbt-run, dbt-test, dbt-docs, test-ml, lint, format,
  validate, clean, help`.
- **#25 `docs/runbook.md`** — procédures on-call (MinIO down, Snowflake
  freshness KO, ml-service 5xx, Mongo down, Airflow scheduler bloqué),
  contacts fictifs, escalade data-breach GDPR Art. 33.
- **#21 `docs/DPO.md`** — contacts DPO + CISO fictifs cohérents avec
  SPECIFICATIONS §4.1, registre des traitements (Art. 30), procédure
  d'exercice des droits.

### Added — CI & qualité

- **#14 `.github/workflows/ci.yml`** — 4 jobs : `docker compose config`,
  `dbt parse`, `py_compile` sur DAGs+ml-service+scripts, `pytest ml-service`.
- **#15 `pyproject.toml`** — config ruff + black + isort + pytest.
- **#16 `.sqlfluff`** — templater dbt, dialect snowflake, capitalisation
  keywords/types=upper, identifiers=lower.
- **#22 Section "Accessibilité"** ajoutée au README : structure sémantique
  Markdown, tableaux avec en-têtes, description textuelle des diagrammes
  ASCII, liens explicites, conformité RGAA 4.1 / WCAG 2.1 AA.

### Notes

- **#19 ml-service logs** — revérifié, `print()` déjà remplacés par
  `logger.info/warning/exception` en v3-hauts. Pas de modification.

### Fichiers ajoutés

```
.github/workflows/ci.yml
.sqlfluff
pyproject.toml
Makefile
docker/mongo/init-mongo.sh                        (remplace init-mongo.js)
dbt/stripe_analytics/models/staging/stg_refunds.sql
dbt/stripe_analytics/models/staging/stg_disputes.sql
dbt/stripe_analytics/models/staging/stg_exchange_rates.sql
dbt/stripe_analytics/models/staging/stg_transactions_rejected.sql
dbt/stripe_analytics/models/staging/_staging.yml
docs/DPO.md
docs/runbook.md
queries/README.md
queries/snowflake/revenue_by_region.sql
queries/snowflake/top_fraud_merchants.sql
queries/snowflake/customer_cohort_retention.sql
queries/snowflake/fraud_rate_by_mcc_country.sql
queries/postgres/audit_log_review.sql
queries/mongodb/clickstream_funnel.js
queries/mongodb/top_fraud_customers.js
```

---

## [v3-hauts] — 2026-04-19

Correction des 20+ issues de sévérité **HAUT** identifiées par l'audit
du repo v2 (cf. `audit_stripe_data_architecture_v2.docx`).

### Fixed — Bugs techniques

- **[HAUT] Healthcheck Mongo fragile** (`docker-compose.yml`) — quoting
  plain-scalar avec pipes imbriqués. Remplacé par `CMD-SHELL` explicite :
  `mongosh --quiet --eval 'db.runCommand({ping:1}).ok' | grep -q 1`.

- **[HAUT] Kafka depends_on sans condition** — `zookeeper.depends_on`
  short-form ne garantissait pas que Zookeeper soit prêt. Ajouté un
  healthcheck Zookeeper (`ruok`) + `kafka.depends_on.zookeeper.condition:
  service_healthy` + même pattern sur `kafka-ui`.

- **[HAUT] Images non pinnées** — `mongo-express:latest`,
  `minio/minio:latest`, `provectuslabs/kafka-ui:latest`,
  `prom/prometheus:latest`, `grafana/grafana:latest` toutes pinnées à
  des versions datées (reproductibilité v3).

- **[HAUT] Prometheus scrape Kafka invalide** (`prometheus.yml`) — job
  `kafka:9092` pointait sur le port broker binaire (pas HTTP Prometheus).
  Retiré, avec note explicite en commentaire : JMX Exporter requis en
  Phase 2.

- **[HAUT] Prometheus scrape Airflow invalide** — endpoint `/admin/metrics/`
  est Airflow 1.x. Retiré, avec note Phase 2 (`statsd_exporter` ou plugin).

- **[HAUT] Ajout job MinIO Prometheus** — exploite l'endpoint natif
  `/minio/v2/metrics/cluster`.

- **[HAUT] Grafana datasource sans uid** — dashboards référençaient
  `uid: prometheus` alors que le YAML de provisioning ne le fixait pas.
  Ajouté `uid: prometheus` dans `datasources.yml`.

- **[HAUT] Variable `SNOWFLAKE_AIRBYTE_PASSWORD` manquante** — référencée
  par `airbyte/configs/snowflake_destination.yaml` mais absente du
  `.env.example`. Ajoutée avec commentaire explicatif.

- **[HAUT] Terraform RDS sans security group dédié** — utilisait le SG
  default du VPC. Création d'un `aws_security_group.postgres` avec ingress
  restreint (var `allowed_cidr_blocks_postgres`, default `10.0.0.0/8`).

- **[HAUT] Terraform password plaintext** — `var.postgres_password` était
  stocké en clair dans le state. Remplacé par
  `manage_master_user_password = true` (AWS Secrets Manager géré par RDS,
  rotation automatique, clé KMS).

- **[HAUT] Terraform VPC default** — conservé pour la démo avec
  commentaire explicite "non-conforme PCI-DSS v4.0 Req 1.2". TODO phase 2
  documenté en tête de fichier.

- **[HAUT] DAG `trigger_transform` bidon** — était un `BashOperator echo`
  avec commentaire trompeur. Remplacé par un vrai
  `TriggerDagRunOperator(trigger_dag_id="transform_dbt",
  wait_for_completion=False, reset_dag_run=True)`.

- **[HAUT] DAG `ml_fraud_scoring` 100 % pseudo-code** — tous les
  `PythonOperator` étaient des `print()`. Remplacés par une implémentation
  réelle :
    - `extract_training_dataset` : SnowflakeHook + `SELECT` sur
      `FACT_TRANSACTION` + JOIN dims, export parquet.
    - `compute_features` : pandas agg + upsert MongoDB
      `ml_features_customer` via `bulk_write(UpdateOne)`.
    - `train_model` : XGBClassifier + StratifiedKFold cross-val AUC,
      pickle du modèle, push XCom.
    - `validate_model` : gate AUC ≥ 0.85.
    - `deploy_canary` : upload S3/MinIO `ml-artifacts/fraud/v{date}/` +
      registre MongoDB avec `canary_pct=5`.
    - `monitor_drift` : PSI (Population Stability Index) sur
      `amount_usd` et `fraud_score` vs distribution de référence.

- **[HAUT] Docstring ML service mensongère** — annonçait "XGBoost + Kafka
  consumer" alors qu'aucun import correspondant. Docstring réécrite pour
  refléter la réalité, ET chargement dynamique XGBoost réellement
  implémenté avec fallback rule-based explicite.

### Fixed — Sécurité

- **[HAUT] ML service `/score` sans authentification** — ajout
  authentification par header `X-API-Key` (liste CSV dans `ML_API_KEYS`)
  + rate limit 120 req/min/IP via `slowapi`. Flag `ML_DEV_ALLOW_NO_AUTH=1`
  pour démo locale. Compteur Prometheus `fraud_score_auth_failures_total`.

- **[HAUT] Passwords fallback en clair** — `ml-service/app/main.py`
  contenait `mongodb://admin:change_me@mongo:27017` en fallback.
  Supprimé : fail-fast si `MONGO_URI` absent.

- **[MOYEN→HAUT] Mongo-express exposé sur toutes les interfaces** —
  port bindé sur `0.0.0.0:8081` avec `admin/admin` hardcodé. Désormais
  bind `127.0.0.1:8081` + credentials via `MONGO_EXPRESS_USER` /
  `MONGO_EXPRESS_PASSWORD`.

- **[MOYEN→HAUT] ML service container en root** — Dockerfile ajoute un
  user `appuser` UID 1000 non-root.

### Fixed — Qualité / cohérence docs

- **[HAUT] Incohérence docstring ML + ARCHITECTURE.md §2.8** — aligné :
  XGBoost avec fallback rule-based documenté des deux côtés.

- **[HAUT] ARCHITECTURE.md §2.5 mentionne Kafka CDC via Debezium** —
  reformulé : "topics provisionnés pour un futur connecteur Debezium,
  actuellement non câblé ; le pipeline de production utilise Airbyte
  batch".

- **[HAUT] ARCHITECTURE.md §2.9 mentionne Kafka JMX + Airflow** —
  reformulé : exporters additionnels requis en Phase 2.

- **[HAUT] ARCHITECTURE.md §3.2 mentionne Kafka `events.fraud_scored`
  écrit par le ML service** — reformulé : "publication vers Kafka non
  encore implémentée, topic provisionné pour Phase 2".

- **[HAUT] Aucun test unitaire Python** — ajout de
  `ml-service/tests/test_scoring.py` avec pytest : 10 cases couvrant
  `score_rulebased` (baseline, high_amount, high_risk_country,
  velocity), `decide` (7 seuils paramétrés), `fetch_features`
  (fallback/présent), endpoint `/health` via TestClient.
  Nouveau fichier `ml-service/requirements-dev.txt`.

### Added

- `airflow/Dockerfile` étendu avec xgboost 2.1.1, sklearn 1.5.2,
  pandas 2.2.3, pyarrow, boto3, pymongo, numpy — deps réelles requises
  par `ml_fraud_scoring`.

- `docker-compose.yml` :
  - Variable d'environnement `AIRFLOW_CONN_SNOWFLAKE_DEFAULT` côté
    webserver + scheduler (pour `SnowflakeHook`).
  - Env vars `MINIO_ENDPOINT`, `MINIO_USER`, `MINIO_PASSWORD`,
    `MONGO_URI` côté Airflow.
  - Volume `ml_models` monté sur `ml-service:/app/models` (permet au
    DAG `ml_fraud_scoring` de pousser un pickle consommé par le service).
  - Env vars ML (`ML_API_KEYS`, `ML_DEV_ALLOW_NO_AUTH`,
    `ML_MODEL_PATH`, `LOG_LEVEL`).
  - `AIRFLOW__WEBSERVER__SECRET_KEY` désormais aussi sur scheduler.

- `.env.example` : `SNOWFLAKE_AIRBYTE_PASSWORD`, `ML_API_KEYS`,
  `ML_DEV_ALLOW_NO_AUTH`, `LOG_LEVEL`, `MONGO_EXPRESS_USER`,
  `MONGO_EXPRESS_PASSWORD`.

- `terraform/main.tf` : output `rds_master_secret_arn`,
  `postgres_security_group_id` ; backend S3 documenté en commentaire.

### Changed

- `ml-service/app/main.py` : logging structuré JSON
  (`python-json-logger`), fail-fast si `MONGO_URI` manquante, chargement
  XGBoost dynamique, `datetime.now(timezone.utc)` (remplace
  `datetime.utcnow()` déprécié).

- `ml-service/requirements.txt` : ajout `slowapi`, `python-json-logger`,
  `xgboost==2.1.1`, `numpy<2.0`.

- `scripts/transaction-generator.py` : envoie `X-API-Key` si
  `ML_API_KEYS` est set dans l'environnement.

- `airflow/dags/ingest_to_snowflake.py` : authentification Airbyte OSS
  (bearer token via `client_id`/`client_secret`), `sla` retiré
  (déprécié Airflow 2.9+).

### Still pending (prochaine passe — sévérité MOYEN/BAS)

- `fact_transaction.sql` comparaison `TIMESTAMP` vs `TIMESTAMP_TZ`.
- `dim_date.sql` : `DAYOFWEEK` → `DAYOFWEEKISO`.
- Création de `stg_refunds.sql`, `stg_disputes.sql`, `stg_exchange_rates.sql`.
- Seeds payment_methods dans `docker/postgres/seed.sql`.
- Script `.sh` d'init Mongo pour éviter le password hardcodé
  dans `init-mongo.js`.
- `.github/workflows/ci.yml` basique.
- Export visuel ERD (`docs/ERD.png`) et diagramme d'architecture.
- Dossier `queries/` avec requêtes SQL business démonstratives.

---

## [v3-critical] — 2026-04-19

Correction des 4 issues **CRITIQUES** identifiées par l'audit (bloquent
un `docker compose up` fonctionnel).

### Fixed

- **[CRITIQUE] `docker-compose.yml` — Healthcheck MinIO cassé**
  `mc` n'est pas dans l'image `minio/minio:latest`. Remplacé par
  `curl -fsS http://localhost:9000/minio/health/live`.

- **[CRITIQUE] `minio/init/setup-buckets.sh` — Init buckets cassée**
  Même racine. Ajout d'un service `minio-init` dans compose
  (image `minio/mc`, one-shot, créé les buckets au démarrage). Script
  shell réécrit pour `docker run --network` en usage manuel.

- **[CRITIQUE] Airflow sans dbt ni providers**
  Image standard ne contient ni dbt, ni dbt-snowflake, ni providers,
  ni requests. Création de `airflow/Dockerfile` custom avec
  `apache-airflow-providers-snowflake==5.6.0`,
  `apache-airflow-providers-http==4.12.0`, `dbt-core==1.8.7`,
  `dbt-snowflake==1.8.4`, `requests`. Les 3 services Airflow pointent
  vers `build: ./airflow` avec tag `stripe/airflow-custom:2.9.2`.

- **[CRITIQUE] Conflit port 8000 ml-service vs Airbyte**
  Déplacement ml-service : port externe `8000:8000` → `8001:8000`.
  Ajout healthcheck Compose-level. Documentation mise à jour
  (README, DEPLOYMENT, transaction-generator default `--ml-url`).

---

## [v2] — 2026-04-11

Version initiale soumise à audit (46 fichiers, 3 551 lignes).
