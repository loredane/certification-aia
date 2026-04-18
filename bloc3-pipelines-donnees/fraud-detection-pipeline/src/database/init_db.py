"""
Script pour créer la base et les tables PostgreSQL.
A lancer une fois au setup du projet.
"""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import DB_CONFIG


def create_database():
    """Crée la BDD fraud_detection si elle existe pas encore."""
    conn = psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database="postgres",  # on se connecte d'abord à postgres par défaut
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_CONFIG["database"],))
    if not cur.fetchone():
        cur.execute(f"CREATE DATABASE {DB_CONFIG['database']}")
        print(f"Base '{DB_CONFIG['database']}' créée.")
    else:
        print(f"Base '{DB_CONFIG['database']}' existe déjà.")

    cur.close()
    conn.close()


def create_tables():
    """Crée toutes les tables nécessaires au pipeline."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Table principale : on stocke les transactions + les résultats de prédiction
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            trans_date_trans_time TIMESTAMP,
            cc_num VARCHAR(20),
            merchant VARCHAR(255),
            category VARCHAR(100),
            amt DECIMAL(10, 2),
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            gender VARCHAR(10),
            street VARCHAR(255),
            city VARCHAR(100),
            state VARCHAR(50),
            zip VARCHAR(10),
            lat DECIMAL(10, 6),
            long DECIMAL(10, 6),
            city_pop INTEGER,
            job VARCHAR(255),
            dob DATE,
            trans_num VARCHAR(50) UNIQUE,
            unix_time BIGINT,
            merch_lat DECIMAL(10, 6),
            merch_long DECIMAL(10, 6),
            fraud_probability DECIMAL(5, 4),
            is_fraud_predicted BOOLEAN DEFAULT FALSE,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            model_version VARCHAR(50),
            data_quality_status VARCHAR(20) DEFAULT 'pending'
        );
    """)

    # Index sur les colonnes qu'on requête souvent
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions (trans_date_trans_time);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trans_fraud ON transactions (is_fraud_predicted);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trans_ingested ON transactions (ingested_at);")

    # Table pour logger les exécutions du pipeline (monitoring)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_logs (
            id SERIAL PRIMARY KEY,
            dag_id VARCHAR(100),
            task_id VARCHAR(100),
            execution_date TIMESTAMP,
            status VARCHAR(20),
            records_processed INTEGER DEFAULT 0,
            records_failed INTEGER DEFAULT 0,
            duration_seconds DECIMAL(10, 2),
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Table pour les résultats des checks de qualité
    cur.execute("""
        CREATE TABLE IF NOT EXISTS data_quality_logs (
            id SERIAL PRIMARY KEY,
            check_name VARCHAR(100),
            check_type VARCHAR(50),
            passed BOOLEAN,
            details JSONB,
            records_checked INTEGER,
            records_passed INTEGER,
            pass_rate DECIMAL(5, 4),
            execution_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Dead letter queue : les transactions rejetées par la validation
    # comme ça on peut les analyser après sans bloquer le pipeline
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dead_letter_queue (
            id SERIAL PRIMARY KEY,
            raw_data JSONB,
            error_type VARCHAR(100),
            error_message TEXT,
            source VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Tables créées.")


if __name__ == "__main__":
    create_database()
    create_tables()
