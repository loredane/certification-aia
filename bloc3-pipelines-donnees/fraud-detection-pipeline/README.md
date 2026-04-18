# Automatic Fraud Detection — Pipeline de Données

**Bloc 3 — Certification AIA (RNCP38777)**

## Contexte

La fraude CB c'est plus d'1 milliard d'euros/an dans l'UE (ECB 2019). Ce projet met en place un pipeline de données complet pour détecter les fraudes en temps réel et produire des rapports quotidiens.

> **Important** : la priorité c'est le pipeline de données, pas le modèle ML.

## Architecture

```
Sources (API + CSV) 
    ↓
Airflow (orchestration - 3 DAGs)
    ↓
Data Quality → ML Predict → PostgreSQL
    ↓
Notifications (temps réel) + Rapport (batch)
```

**3 DAGs Airflow :**
- `stream_ingest` : ETL temps réel, tourne chaque minute. Pull l'API → valide → prédit → stocke → alerte si fraude
- `daily_report` : ELT batch, tous les matins à 7h. Agrège les transactions de la veille et envoie un rapport
- `train_model` : ML, hebdomadaire. Réentraîne le modèle et le sauvegarde dans MLflow

## Structure du projet

```
├── dags/                     # DAGs Airflow
│   ├── dag_stream_ingest.py  # temps réel
│   ├── dag_daily_report.py   # batch quotidien
│   └── dag_train_model.py    # entrainement ML
├── src/
│   ├── database/             # init PostgreSQL + requêtes SQL
│   ├── data_quality/         # validation des données
│   ├── ml/                   # preprocessing, train, predict
│   ├── notifications/        # alertes fraude + rapport email
│   └── utils/                # client API
├── config/                   # configuration centralisée
├── tests/                    # tests unitaires
├── docker-compose.yml        # infra Docker (Postgres + MLflow + Airflow)
├── Dockerfile
└── requirements.txt
```

## Lancement

```bash
# Avec Docker (recommandé)
docker-compose up -d

# Airflow: http://localhost:8080 (admin/admin)
# MLflow:  http://localhost:5000

# Sans Docker
pip install -r requirements.txt
python src/database/init_db.py
python src/ml/train.py
```

## Stack technique

| Composant | Techno | Pourquoi |
|-----------|--------|----------|
| Orchestration | Airflow | Standard industrie, DAGs en Python |
| Base de données | PostgreSQL | ACID, SQL, adapté OLTP + analytique |
| ML Lifecycle | MLflow | Versioning des modèles |
| ML | Scikit-learn | Pipeline réutilisable |
| Data Quality | Validation custom | Checks schéma + règles métier |
| Infra | Docker Compose | Reproductibilité |

## Data Quality

- **En entrée** : validation schéma, règles métier (montant > 0, coordonnées valides, etc.)
- **En sortie** : vérification des prédictions (probabilité dans [0,1])
- **Erreurs** : dead letter queue pour les données rejetées, retry automatique, logs dans data_quality_logs

## Tests

```bash
pytest tests/ -v
```

## Références

- DAMA-DMBOK2 ch.8 (Data Integration), ch.13 (Data Quality), ch.6 (Storage)
- Fundamentals of Data Engineering (Reis & Housley) ch.7, ch.8, ch.2
