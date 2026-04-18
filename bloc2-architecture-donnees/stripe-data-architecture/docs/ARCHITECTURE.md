# Architecture · Stripe Data Platform

Choix d'architecture et justifications pour le cas Stripe fictif du Bloc 2 AIA (RNCP38777). Je m'appuie sur le **DAMA-DMBOK2** et *Fundamentals of Data Engineering* (Reis & Housley, O'Reilly, 2022) — références citées à chaque choix structurant.

## 1. Besoins architecturaux

### 1.1 Contraintes techniques

L'OLTP doit encaisser plusieurs milliers de transactions par seconde avec une latence p99 sous 200 ms et une dispo cible à 99.99%. ACID non négociable : on parle de flux financiers, pas d'un blog.

L'OLAP tourne sur des milliards de lignes historiques. Cible : sous la seconde sur les vues matérialisées pour les dashboards, quelques secondes acceptables sur l'ad hoc.

Le NoSQL encaisse des volumes délirants — logs, clickstream, features ML — de l'ordre de centaines de millions de documents par jour, avec un schéma applicatif qui bouge en permanence.

### 1.2 Contraintes opérationnelles

La stack doit se lancer en une commande (DAMA ch.6 §1.3.2) — sinon, pas de dev ni de tests reproductibles. Les data engineers doivent observer le pipeline bout-en-bout sans changer de console. Les migrations schématiques se font sans downtime.

### 1.3 Contraintes normatives

Trois réglementations applicables :

- **GDPR** — UE, droit à l'oubli, portabilité, consentement
- **PCI-DSS** — données cartes, tokenisation obligatoire, audit trail append-only conservé 1 an minimum
- **CCPA** — Californie, proche du GDPR

Implémentation détaillée dans `SECURITY.md`.

## 2. Cahier des charges

| Exigence | Cible | Réalisation |
|---|---|---|
| Débit OLTP | 5 000 tx/s | PostgreSQL + partitionnement mensuel + index partiels + réplication logique |
| Latence OLTP | p99 < 200 ms | Index compound `(merchant, created_at)` et `(customer, created_at)` |
| Latence dashboard OLAP | < 1 s | Materialized views `SummingMergeTree` ClickHouse |
| Rétention conformité | 7 ans | TTL 7 ans sur `fact_transaction`, audit append-only |
| Traçabilité PCI-DSS | 100% | Trigger générique + table append-only |
| Tokenisation PAN | Obligatoire | `payment_method` : token + last4 uniquement, jamais de PAN |
| Chiffrement at rest | AES-256 | `pgcrypto` (PostgreSQL), TDE moteur cloud en prod |
| Chiffrement in transit | TLS 1.2+ | Connection strings prod |
| RBAC | 3 rôles minimum | `app_read`, `app_write`, `analytics_ro` + rôles MongoDB dédiés |
| Data quality | Tests auto | dbt tests + réconciliation Airflow OLTP ↔ OLAP |
| Monitoring | Temps réel | Prometheus + 2 dashboards Grafana |

## 3. Architecture en couches

Choix global : **polyglot persistence** (DAMA ch.6 §1.3.6). Pas de BDD universelle — une techno par type de workload. PostgreSQL pour le transactionnel, ClickHouse pour l'analytique, MongoDB pour le non-structuré.

### 3.1 Sources

Événements entrants : API paiement, portail merchant, apps mobiles, webhooks partenaires. Tout atterrit dans PostgreSQL après validation applicative.

### 3.2 OLTP — PostgreSQL

Schéma normalisé en 3NF (DAMA ch.5 §1.3.5.3), découpé en trois schémas logiques : `core` (entités métier), `reference` (données de référence SCD), `audit` (append-only).

`core.transaction` est **partitionnée par mois** (DAMA ch.6 §2.3). Deux raisons : drop des partitions expirées pour la rétention, et le planner ne lit que la bonne partition sur les requêtes récentes. Chaque partition a ses index sur `(merchant_id, created_at)` et `(customer_id, created_at)`, plus un **index partiel** sur `fraud_score > 0.7` — celui-là divise la taille d'index par 50 en gros, parce que la fraude c'est quelques % du volume.

La **publication logique** PostgreSQL (`stripe_publication`) expose les tables critiques à Debezium sans toucher au chemin transactionnel applicatif.

### 3.3 CDC — Debezium + Kafka

Debezium lit le WAL logique et publie les events dans Kafka (DAMA ch.8 §1.3.1.4). Quatre topics : `stripe.core.transaction`, `stripe.core.customer`, `stripe.core.merchant`, `stripe.core.payment_method`.

Transformation **ExtractNewRecordState** (`unwrap`) sur le connecteur : les consumers reçoivent directement l'état courant, pas l'enveloppe `before` / `after`. Ça simplifie tout downstream.

### 3.4 OLAP — ClickHouse

Modélisation dimensionnelle Kimball (DAMA ch.5 §1.3.5.5, *Fundamentals* ch.8). Au centre, `fact_transaction` au grain transaction. Six dimensions : date, customer, merchant, payment_method, currency, geography.

`dim_customer` et `dim_merchant` sont en **SCD Type 2** (`valid_from`, `valid_to`, `is_current`). Les changements d'adresse, de KYC status ou de business_name sont historisés — sinon on perd l'historique dès qu'un merchant change de nom.

Deux **materialized views** pré-agrègent pour les dashboards :

- `mv_daily_revenue` : revenue par merchant × pays × devise
- `mv_hourly_fraud` : patterns de fraude par cohorte

Les deux utilisent `SummingMergeTree` — ClickHouse agrège à l'insertion, pas à la requête. C'est ce qui tient la latence dashboard sous la seconde.

### 3.5 NoSQL — MongoDB

Cinq collections, chacune avec le pattern adapté au use-case (DAMA ch.5 §1.3.6.2) :

- `event_logs` → time-series, TTL 90 jours, index compound `(service, level, timestamp)`
- `clickstream_sessions` → **embedding** : les events sont imbriqués dans la session, parce qu'on accède toujours à la session complète
- `ml_feature_store` → **referencing** : juste le `customer_id`, pas les données customer (elles restent dans l'OLTP, source de vérité)
- `customer_feedback` → **full-text search** avec poids (`subject:10`, `body:5`)
- `fraud_alerts` → collection **time-series native** MongoDB, granularité minute

Règle que j'ai appliquée pour embedding vs referencing : embed si accédé ensemble et borné, reference si accédé séparément ou croissance illimitée.

### 3.6 Orchestration — Airflow

Deux DAGs.

`dag_oltp_to_olap_daily` tourne à 2h UTC : extract des transactions J-1, load dans ClickHouse staging, transform via dbt, tests data quality, puis **réconciliation** (tolérance 0.01%) entre la somme du revenue OLTP et OLAP. Si l'écart dépasse, le DAG échoue — mieux vaut une alerte qu'un dashboard faux.

`dag_ml_features_hourly` calcule les features ML agrégées (rolling windows 7j / 30j / 180j) et les upsert dans le feature store MongoDB. Ensuite il valide la **fraîcheur** : au moins 90% des customers actifs doivent avoir des features de moins de 2h, sinon alerte.

### 3.7 Transformation — dbt

Les marts `revenue_daily` et `fraud_analysis` encapsulent la logique métier en SQL versionné, testable, documenté. Les tests dbt (`not_null`, `unique`, `accepted_range`) attrapent les régressions sans écrire du Python custom.

### 3.8 Monitoring — Prometheus + Grafana

Deux dashboards **provisionnés** en JSON (pas cliqués à la main dans l'UI, donc reproductibles) :

- **Business** — transactions 24h, gross revenue, success rate, high-risk fraud rate, revenue par heure, top 10 pays
- **Infra** — services up/down, scrape duration par job, timeline up

## 4. Principes directeurs

Les choix s'appuient sur les principes de *Fundamentals of Data Engineering* ch.3.

**Loosely coupled systems.** Kafka au centre. Chaque couche évolue indépendamment. Passer PostgreSQL à MySQL n'impacterait que l'ingestion côté Debezium, rien en aval.

**Reversible decisions.** Tout est versionné : dbt models dans Git, schemas ClickHouse recréables, dashboards Grafana en JSON. Rien de cliqué dans une UI qu'il faudrait reproduire à la main.

**Architect for scalability.** Partitioning à chaque couche : mensuel PostgreSQL, mensuel ClickHouse, TTL MongoDB, partitions Kafka par topic. On peut passer à l'échelle sans tout refaire.

**Security by design.** Chiffrement, RBAC, audit intégrés dès l'init de chaque couche. Pas rajoutés après coup.

## 5. Couverture RNCP

| Compétence Bloc 2 | Où |
|---|---|
| Besoins architecturaux | §1 |
| Cahier des charges | §2 |
| Modèles logiques / physiques | `docker/postgres/init.sql`, `clickhouse/init/01_star_schema.sql`, `mongodb/init/01_collections.js` |
| Structures BDD adaptées | Polyglot persistence, §3 |
| Déploiement serveurs | `docker-compose.yml` |
| Clusters de calcul | Kafka partitionné, ClickHouse sharding-ready |
| Surveillance | Prometheus + 2 dashboards Grafana |
| Doc accessible | Ce document |

## 6. Accessibilité de la doc

Respect des exigences WCAG 2.1 AA applicables à un doc technique : hiérarchie de titres logique sans saut de niveau, alt-texts sur les diagrammes SVG, tableaux avec en-têtes, aucune info transmise par la couleur seule, contraste suffisant dans Grafana (thème sombre AA par défaut).
