# Stripe Data Architecture · From SQL to NoSQL

Projet Bloc 2 de la certification **AIA (RNCP38777, Niveau 7)**. Cas d'étude fictif sur une plateforme type Stripe — intégration OLTP + OLAP + NoSQL, pipelines batch et streaming.

Toute la stack tourne en local avec une commande : `make up`. Onze services Docker Compose.

> Stripe est cité uniquement comme cas fictif pour l'exercice. Rien n'est affilié ni endorsé par Stripe, Inc.

## Stack

| Couche | Techno | Rôle |
|---|---|---|
| OLTP | PostgreSQL 16 | Schéma 3NF, WAL logique pour CDC, audit append-only |
| CDC | Debezium | PostgreSQL → Kafka |
| Streaming | Kafka + Zookeeper | Bus d'événements, 4 topics |
| OLAP | ClickHouse | Star schema Kimball, SCD2, materialized views |
| NoSQL | MongoDB | Feature store ML, logs, clickstream, feedback, fraud alerts |
| Orchestration | Airflow | DAG ELT quotidien + DAG features ML horaire |
| Transformation | dbt | Modèles marts + tests data quality |
| Génération | Python | Transactions réalistes pour la démo |
| Monitoring | Prometheus + Grafana | 2 dashboards provisionnés (business + infra) |

## Quickstart

```bash
cp .env.example .env
make up                 # stack complète
make init-cdc           # Debezium, une fois Kafka up
make generate           # transactions de démo

# UIs
# Airflow   → http://localhost:8080 (airflow / airflow)
# Grafana   → http://localhost:3000 (admin / admin)
# Kafka UI  → http://localhost:8081
```

Stopper : `make down`. Nettoyer les volumes : `make clean`.

## Structure

```
stripe-data-architecture/
├── README.md
├── LICENSE (MIT)
├── Makefile
├── docker-compose.yml
├── .env.example
│
├── docker/
│   ├── postgres/
│   │   ├── init.sql          — Schéma 3NF + partitions + RBAC + audit
│   │   └── seed.sql          — Pays, devises, payment methods
│   ├── debezium/connector.json
│   ├── airflow/dags/
│   │   ├── dag_oltp_to_olap.py
│   │   └── dag_ml_features.py
│   ├── prometheus/prometheus.yml
│   └── grafana/ (dashboards + provisioning)
│
├── clickhouse/init/01_star_schema.sql
├── mongodb/init/01_collections.js
│
├── dbt/stripe_analytics/
│   ├── dbt_project.yml
│   └── models/marts/ (revenue_daily, fraud_analysis + tests)
│
├── generator/ (Dockerfile + generate.py)
│
├── queries/            — Livrable 8 : requêtes SQL/NoSQL business
├── scripts/            — init-debezium.sh + demo.sh (pour la vidéo)
│
└── docs/
    ├── ARCHITECTURE.md
    └── SECURITY.md
```

## Compétences RNCP Bloc 2

- **Identifier les besoins architecturaux** → `docs/ARCHITECTURE.md` §1
- **Cahier des charges** → `docs/ARCHITECTURE.md` §2
- **Modèles logiques et physiques** → `docker/postgres/init.sql` (ERD 3NF), `clickhouse/init/01_star_schema.sql` (Kimball)
- **Structures BDD adaptées** → polyglot persistence OLTP + OLAP + NoSQL
- **Déploiement serveurs** → `docker-compose.yml`
- **Clusters de calcul** → Kafka partitionné, ClickHouse sharding-ready, MongoDB replica set
- **Surveillance performances** → Prometheus + 2 dashboards Grafana
- **Documentation accessible** → Markdown hiérarchisé, alt-texts SVG, pas d'info uniquement par couleur

```

## Licence

MIT. Voir `LICENSE`.
