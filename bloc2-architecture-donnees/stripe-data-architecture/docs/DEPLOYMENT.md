# Guide de déploiement

## 1. Prérequis

- Docker Desktop 4.x (8 Go RAM minimum alloués)
- Python 3.10+
- Compte Snowflake (trial 30 jours gratuit sur https://signup.snowflake.com/)
- Git

## 2. Déploiement local (Docker Compose)

### 2.1. Clone + configuration

```bash
git clone https://github.com/<user>/stripe-data-architecture.git
cd stripe-data-architecture

cp .env.example .env
# Éditer .env avec tes vrais credentials Snowflake
```

### 2.2. Setup Snowflake (une fois)

1. Se connecter sur l'interface web Snowflake
2. Exécuter `snowflake/init/01_setup_snowflake.sql` en tant que `ACCOUNTADMIN`
3. Exécuter `snowflake/init/02_create_raw_tables.sql` en tant que `DATA_ENG_ROLE`
4. Récupérer l'account identifier (ex: `abc12345.eu-west-1`) et le mettre dans `.env`

### 2.3. Démarrage

```bash
# Start stack (~2 min pour tous les services healthy)
docker compose up -d

# Vérifier état
docker compose ps

# Init Kafka topics
chmod +x kafka/topics-init.sh
./kafka/topics-init.sh

# Init MinIO buckets
chmod +x minio/init/setup-buckets.sh
./minio/init/setup-buckets.sh

# Générer du trafic
pip install -r scripts/requirements.txt
python scripts/transaction-generator.py --rate 5 --duration 300
```

### 2.4. Airbyte (optionnel pour la démo)

Airbyte OSS se lance séparément via `abctl` :

```bash
# Install abctl
curl -LsfS https://get.airbyte.com | bash -
abctl local install

# Airbyte UI : http://localhost:8000
# (FIX v3: le ml-service a été déplacé sur 8001 pour libérer 8000)
# Créer deux connexions :
#  1. PostgreSQL source → S3/MinIO destination
#  2. S3/MinIO source → Snowflake destination
```

Pour la démo, on peut **court-circuiter Airbyte** et charger Snowflake directement depuis Python/dbt (plus simple pour la vidéo).

### 2.5. dbt run

```bash
# Depuis l'host (pas le container)
docker exec -it stripe_airflow_scheduler bash
cd /opt/airflow/dbt/stripe_analytics
dbt deps --profiles-dir /opt/airflow/dbt
dbt run --profiles-dir /opt/airflow/dbt --target dev
dbt test --profiles-dir /opt/airflow/dbt --target dev
```

### 2.6. Airflow DAGs

- UI : http://localhost:8080 (airflow / airflow)
- Activer les 3 DAGs : `ingest_to_snowflake`, `transform_dbt`, `ml_fraud_scoring`
- Cliquer "Trigger DAG" pour un test manuel

### 2.7. Vérifier le pipeline

| Service | URL | Quoi vérifier |
|---|---|---|
| Airflow | http://localhost:8080 | DAGs success (vert) |
| Grafana | http://localhost:3000 | Dashboard "Stripe Pipeline Overview" — fraud_score_requests_total > 0 |
| FastAPI ML | http://localhost:8001/docs | Tester endpoint `/score` |
| Mongo Express | http://localhost:8081 | Collection `fraud_alerts` non vide |
| MinIO | http://localhost:9002 | Buckets bronze/silver/gold créés |
| Kafka UI | http://localhost:8082 | Topics list, consumer groups |
| Snowflake | web Snowflake | `SELECT * FROM STRIPE_ANALYTICS.MARTS.FACT_TRANSACTION LIMIT 10;` |

## 3. Déploiement cloud (Terraform AWS)

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Éditer terraform.tfvars

terraform init
terraform plan
terraform apply

# Output :
# - s3_raw_bucket, s3_staging_bucket, s3_archive_bucket
# - rds_endpoint (PostgreSQL)
# - kms_key_arn
```

## 4. Arrêt / reset

```bash
# Arrêter la stack
docker compose down

# Reset complet (efface les volumes — ATTENTION)
docker compose down -v

# Nettoyer Docker
docker system prune -a
```

## 5. Troubleshooting

### Postgres ne démarre pas

```bash
docker compose logs postgres
# Souvent : volume corrompu → docker compose down -v et recommencer
```

### Airflow webserver crash

```bash
# Vérifier la Fernet key dans .env
# Générer une nouvelle :
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### dbt : "account identifier invalid"

Format correct : `<orgname>-<account>` ou `<account>.<region>.<cloud>`
Exemple : `abc12345.eu-west-1` ou `abc12345.eu-west-1.aws`

### ML service ne démarre pas

```bash
docker compose logs ml-service
# Souvent : MongoDB pas encore healthy → restart ml-service
docker compose restart ml-service
```
