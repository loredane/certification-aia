# Stripe Data Architecture — From SQL to NoSQL

> **Certification AIA — RNCP38777 — Bloc 2**
> *Concevoir et déployer des architectures de données pour l'IA*
> Projet fictif : architecture de données unifiée pour Stripe (FinTech, milliards de transactions/an)

---

## 1. Contexte

Stripe doit concilier quatre impératifs contradictoires :

| Impératif | Réponse architecturale |
|---|---|
| Intégrité transactionnelle (ACID) | **PostgreSQL OLTP** — schéma 3NF, réplication |
| Analytique historique massive | **Snowflake DWH** — star schema Kimball |
| Données non structurées (clickstream, logs, features ML) | **MongoDB** — schéma flexible, sharding |
| Détection de fraude temps réel (< 200 ms) | **Kafka + FastAPI** — streaming inference |
| Conformité GDPR / PCI-DSS / CCPA | **Chiffrement AES-256, RBAC, audit immutable** |

## 2. Stack technique

Stack alignée sur le cursus **Jedha Lead Data Science** et les standards industriels :

```
┌─────────────────────────────────────────────────────────────────────┐
│  SOURCES                                                            │
│  APIs paiement · Portail marchand · Apps mobiles · Partenaires      │
└───────────────────────────┬─────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────────┐
│  OLTP — PostgreSQL 16 (3NF, ACID)                                   │
└───────────────┬───────────────────────────────────┬─────────────────┘
                ↓ Airbyte                           ↓ Kafka (CDC)
┌────────────────────────────┐       ┌──────────────────────────────┐
│  DATA LAKE — MinIO (S3)    │       │  STREAMING — Apache Kafka    │
│  Bronze → Silver → Gold    │       │  Topics: transactions,       │
└───────────────┬────────────┘       │  fraud-alerts, clickstream   │
                ↓ Airbyte            └─────────────┬────────────────┘
┌────────────────────────────┐                     ↓
│  DWH — Snowflake           │       ┌──────────────────────────────┐
│  RAW → STAGING → MARTS     │       │  ML SERVICE — FastAPI        │
│  Star schema (dbt)         │       │  Fraud scoring (XGBoost)     │
└───────────────┬────────────┘       └─────────────┬────────────────┘
                ↓                                  ↓
                └──────────────┬───────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────────┐
│  NoSQL — MongoDB (features store, clickstream, feedback, logs)      │
└─────────────────────────────────────────────────────────────────────┘

ORCHESTRATION : Apache Airflow
TRANSFORMATION : dbt (Snowflake SQL)
MONITORING : Prometheus + Grafana
```

## 3. Démarrage rapide

### Prérequis

- Docker Desktop 4.x avec 8 GB RAM minimum
- Compte Snowflake (trial gratuit 30 jours, $400 de crédits)
- Python 3.10+ (pour le générateur de transactions)

### Installation

```bash
# 1. Cloner le repo
git clone https://github.com/<ton-user>/stripe-data-architecture.git
cd stripe-data-architecture

# 2. Copier et renseigner les variables d'environnement
cp .env.example .env
# Éditer .env avec tes credentials Snowflake

# 3. Configurer Snowflake (une seule fois)
# Se connecter à Snowflake et exécuter :
#   snowflake/init/01_setup_snowflake.sql
#   snowflake/init/02_create_raw_tables.sql

# 4. Démarrer la stack locale
docker compose up -d

# 5. Attendre ~2 min que tous les services soient healthy
docker compose ps

# 6. Initialiser les topics Kafka
./kafka/topics-init.sh

# 7. Créer les buckets MinIO
./minio/init/setup-buckets.sh

# 8. Générer du trafic transactionnel
python scripts/transaction-generator.py --rate 10 --duration 600
```

### Accès aux interfaces

| Service | URL | Credentials |
|---|---|---|
| Airflow | http://localhost:8080 | airflow / airflow |
| MinIO Console | http://localhost:9002 | minioadmin / minioadmin |
| Grafana | http://localhost:3000 | admin / admin |
| FastAPI ML | http://localhost:8001/docs | — |
| MongoDB Express | http://localhost:8081 | admin / admin |
| PostgreSQL | localhost:5432 | voir `.env` |

## 4. Structure du repo

```
.
├── docker-compose.yml          # Orchestration locale complète
├── .env.example                # Variables d'environnement (template)
├── docker/
│   ├── postgres/               # Schéma OLTP 3NF + données seed
│   └── mongo/                  # Init NoSQL (collections + indexes)
├── minio/init/                 # Setup buckets S3 (bronze/silver/gold)
├── snowflake/init/             # DDL Snowflake (warehouses, RBAC, tables)
├── airbyte/configs/            # Connecteurs Airbyte (PG → S3 → Snowflake)
├── dbt/stripe_analytics/       # Modèles dbt (staging + marts Snowflake)
├── airflow/dags/               # DAGs d'orchestration
├── kafka/                      # Init topics + producers
├── ml-service/                 # FastAPI scoring fraud detection
├── scripts/                    # Transaction generator, utils
├── monitoring/                 # Prometheus + Grafana dashboards
├── terraform/                  # Déploiement cloud (miroir AWS)
└── docs/                       # Documentation technique étendue
```

## 5. Mapping RNCP — compétences couvertes

| Compétence RNCP Bloc 2 | Implémentation dans ce repo |
|---|---|
| Identifier besoins architecturaux | `docs/ARCHITECTURE.md` — analyse contraintes Stripe |
| Cahier des charges | `docs/SPECIFICATIONS.md` |
| Modèles logiques / physiques | `docker/postgres/init.sql` (ERD 3NF) + `dbt/models/marts/` (star schema) |
| Structures adaptées (perf, sécu, évolutivité) | Sharding Mongo, clustering Snowflake, replicas PG |
| Déploiement serveurs cloud / On-Prem | `docker-compose.yml` (local) + `terraform/` (AWS) |
| Puissance de calcul via clusters | Kafka partitioning, Snowflake multi-warehouse |
| Outils de surveillance | `monitoring/` — Prometheus + Grafana |
| Documentation inclusive | `docs/` — Markdown structuré, alt-text sur diagrammes |

## 6. Références méthodologiques

- **DAMA-DMBOK2** — Data Management Body of Knowledge (2nd edition)
  - Ch. 4 — Data Architecture
  - Ch. 5 — Data Modeling and Design
  - Ch. 6 — Data Storage and Operations
  - Ch. 7 — Data Security
  - Ch. 8 — Data Integration and Interoperability
- **Fundamentals of Data Engineering** — Joe Reis & Matt Housley (O'Reilly, 2022)
  - Ch. 3 — Designing Good Data Architecture
  - Ch. 7 — Ingestion
  - Ch. 8 — Queries, Modeling, Transformation

## 7. Accessibilité

> **FIX v3-mediums #22** — Conformité compétence RNCP "Documenter les spécifications de manière claire et accessible, en tenant compte des besoins des utilisateurs en situation de handicap".

La documentation de ce projet a été rédigée en respectant les bonnes pratiques d'accessibilité suivantes :

- **Structure sémantique** : utilisation de Markdown avec une hiérarchie de titres cohérente (`#`, `##`, `###`) pour que les lecteurs d'écran (NVDA, JAWS, VoiceOver) puissent naviguer efficacement par niveau de titre.
- **Tableaux avec en-têtes explicites** : chaque tableau possède une première ligne d'en-tête (`| Col1 | Col2 |` + `|---|---|`) exploitable par les technologies d'assistance.
- **Diagrammes ASCII décrits en texte** : chaque diagramme technique (architecture, ERD, star schema) est précédé ou suivi d'une description textuelle de ses composants et de ses flux, qui fait office d'alt-text puisque Markdown ne permet pas d'attribut `alt` natif sur les blocs de code.
- **Pas d'information portée uniquement par la couleur** : les captures Grafana éventuelles sont complétées par les seuils numériques en texte (ex: "warn > 5%, critical > 10%").
- **Liens explicites** : les liens hypertextes utilisent des libellés significatifs hors contexte (pas de "cliquez ici"), par ex. `[cahier des charges](docs/SPECIFICATIONS.md)`.
- **Langue déclarée** : documentation en français, termes techniques en anglais (OLTP, star schema...) glosés à leur première occurrence.
- **Contraste et typographie** : la documentation Markdown s'affiche dans le thème choisi par l'utilisateur (GitHub, VS Code, navigateur), ce qui garantit le respect des préférences de contraste système.

Ces choix s'alignent sur le **Référentiel Général d'Amélioration de l'Accessibilité (RGAA 4.1)** et sur les **Web Content Accessibility Guidelines 2.1 niveau AA**.

## 8. Licence

MIT — projet pédagogique, données fictives. Aucun lien officiel avec Stripe Inc.
