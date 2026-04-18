"""
Config du projet - on met tout ici pour pas hardcoder
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODEL_DIR = PROJECT_ROOT / "models"

# --- Postgres ---
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "database": os.getenv("POSTGRES_DB", "fraud_detection"),
    "user": os.getenv("POSTGRES_USER", "airflow"),
    "password": os.getenv("POSTGRES_PASSWORD", "airflow"),
}

DATABASE_URL = (
    f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
    f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
)

# --- API temps réel ---
API_URL = os.getenv(
    "PAYMENTS_API_URL",
    "https://real-time-payments-api.herokuapp.com/current-transactions"
)
API_TIMEOUT = int(os.getenv("API_TIMEOUT", 30))
API_RETRIES = int(os.getenv("API_RETRIES", 3))

# --- MLflow ---
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "fraud-detection")
MODEL_NAME = "fraud-detection-model"

# --- Dataset d'entrainement ---
TRAIN_DATA_URL = os.getenv(
    "TRAIN_DATA_URL",
    "https://lead-program-assets.s3.eu-west-3.amazonaws.com/M05-Projects/fraudTest.csv"
)
TRAIN_DATA_PATH = DATA_DIR / "fraudTest.csv"

# Colonnes du CSV
EXPECTED_COLUMNS = [
    "trans_date_trans_time", "cc_num", "merchant", "category", "amt",
    "first", "last", "gender", "street", "city", "state", "zip",
    "lat", "long", "city_pop", "job", "dob", "trans_num",
    "unix_time", "merch_lat", "merch_long", "is_fraud"
]

# Features numériques pour le modèle
# j'ai gardé que les numériques pour simplifier, on pourrait encoder les catégorielles aussi
MODEL_FEATURES = ["amt", "lat", "long", "city_pop", "unix_time", "merch_lat", "merch_long"]
TARGET_COLUMN = "is_fraud"

# --- Notifs ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_RECIPIENTS = os.getenv("ALERT_RECIPIENTS", "fraud-team@company.com").split(",")

# --- Seuils ---
FRAUD_PROBABILITY_THRESHOLD = float(os.getenv("FRAUD_THRESHOLD", 0.5))
DATA_QUALITY_MIN_PASS_RATE = float(os.getenv("DQ_MIN_PASS_RATE", 0.95))
MAX_NULL_RATIO = float(os.getenv("MAX_NULL_RATIO", 0.05))

AIRFLOW_CONN_POSTGRES = "postgres_fraud"
