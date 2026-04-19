# =============================================================================
# Stripe Airflow image — custom build with dbt + Snowflake + Airbyte providers
# FIX v3: l'image standard apache/airflow:2.9.2-python3.11 ne contient ni dbt,
#          ni dbt-snowflake, ni les providers utilisés par les DAGs.
#          Cette image custom les ajoute, tout en respectant les règles
#          d'installation documentées par Airflow (constraints file).
# =============================================================================
FROM apache/airflow:2.9.2-python3.11

USER root

# Outils système utiles (curl pour healthchecks, git pour dbt deps éventuels)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Versions pinnées — stack reproductible
ARG AIRFLOW_VERSION=2.9.2
ARG PYTHON_VERSION=3.11

# Fichier de contraintes officiel Airflow pour éviter les conflits de deps
ARG CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

# Providers Airflow (Snowflake + HTTP pour Airbyte)
RUN pip install --no-cache-dir \
      --constraint "${CONSTRAINT_URL}" \
      apache-airflow-providers-snowflake==5.6.0 \
      apache-airflow-providers-http==4.12.0

# dbt-snowflake — installé SANS la contrainte Airflow car dbt a sa propre
# matrice de dépendances (protobuf, networkx, jinja2 notamment).
# En contrepartie, on pinne explicitement la version pour éviter la dérive.
RUN pip install --no-cache-dir \
      "dbt-core==1.8.7" \
      "dbt-snowflake==1.8.4" \
      "requests>=2.32,<3"

# FIX v3-hauts: dependances ML pour le DAG ml_fraud_scoring
# (xgboost, sklearn, pandas, boto3, pymongo, pyarrow pour parquet)
RUN pip install --no-cache-dir \
      "xgboost==2.1.1" \
      "scikit-learn==1.5.2" \
      "pandas==2.2.3" \
      "pyarrow==17.0.0" \
      "boto3==1.35.49" \
      "pymongo==4.8.0" \
      "numpy<2.0"

# Vérification rapide en phase de build (échoue tôt si quelque chose casse)
RUN dbt --version && python -c "import requests, snowflake.connector, xgboost, sklearn, pandas, boto3, pymongo"
