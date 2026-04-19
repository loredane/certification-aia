"""
Client pour récupérer les paiements depuis l'API temps réel.
L'API renvoie les transactions en cours, mise à jour chaque minute.

Ce client implémente un pattern de type circuit breaker : quand l'API externe
est indisponible, on bascule sur un mode fallback qui rejoue des transactions
depuis le dataset fraudTest.csv. Ce mode est crucial en prod quand une source
externe tombe, pour que le pipeline continue de tourner.

Ref. Reis & Housley Ch.5 : gestion des dépendances externes et résilience.
"""
import requests
import time
import logging
import random
import os
import pandas as pd

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import API_URL, API_TIMEOUT, API_RETRIES

logger = logging.getLogger(__name__)

# Chemin du CSV de fallback, monté comme volume dans le conteneur Airflow
FALLBACK_CSV_PATH = "/opt/airflow/data/fraudTest.csv"
_fallback_df = None  # cache du CSV en memoire
_fraud_df = None      # sous-ensemble: transactions frauduleuses
_legit_df = None      # sous-ensemble: transactions legitimes


def _load_fallback_data():
    """Charge le CSV en memoire une seule fois, separe fraudes et non-fraudes
    pour pouvoir controler le ratio en mode demo."""
    global _fallback_df, _fraud_df, _legit_df
    if _fallback_df is None:
        if not os.path.exists(FALLBACK_CSV_PATH):
            logger.error(f"CSV fallback introuvable: {FALLBACK_CSV_PATH}")
            return None
        logger.info(f"Chargement du CSV fallback en memoire")
        full_df = pd.read_csv(FALLBACK_CSV_PATH)
        # On separe avant de drop la colonne is_fraud
        if "is_fraud" in full_df.columns:
            _fraud_df = full_df[full_df["is_fraud"] == 1].drop(columns=["is_fraud"]).reset_index(drop=True)
            _legit_df = full_df[full_df["is_fraud"] == 0].drop(columns=["is_fraud"]).reset_index(drop=True)
            _fallback_df = full_df.drop(columns=["is_fraud"]).reset_index(drop=True)
        else:
            _fallback_df = full_df.reset_index(drop=True)
            _fraud_df = full_df.iloc[0:0]
            _legit_df = full_df.reset_index(drop=True)
        logger.info(f"{len(_fallback_df)} transactions disponibles ({len(_fraud_df)} fraudes, {len(_legit_df)} legitimes)")
    return _fallback_df


def _fallback_from_csv(n=1, fraud_ratio=0.3):
    """Retourne n transactions aleatoires avec un ratio de fraudes controle.
    En demo, on force un ratio de 30% pour que le pipeline complet se declenche
    regulierement (alertes, insertions, etc). En prod, l API temps reel
    renverrait le vrai ratio de la population (0.39%)."""
    _load_fallback_data()
    if _fallback_df is None or len(_fallback_df) == 0:
        return []

    from datetime import datetime
    transactions = []
    for _ in range(n):
        if random.random() < fraud_ratio and _fraud_df is not None and len(_fraud_df) > 0:
            sample = _fraud_df.sample(n=1)
        else:
            sample = _legit_df.sample(n=1)
        transactions.extend(sample.to_dict(orient="records"))

    ts = int(time.time() * 1000)
    for i, txn in enumerate(transactions):
        original = txn.get("trans_num", "unknown")
        txn["trans_num"] = f"REPLAY-{ts}-{i}-{original[:16]}"
        txn["trans_date_trans_time"] = datetime.now().isoformat(timespec="seconds")
    logger.info(f"Fallback CSV active: {len(transactions)} transactions injectees (replay, fraud_ratio={fraud_ratio})")
    return transactions


def fetch_current_transactions(url=API_URL, timeout=API_TIMEOUT, retries=API_RETRIES, use_fallback=True):
    """
    Appelle l'API et retourne la liste des transactions.
    Retry avec backoff exponentiel si ca echoue.
    Si l'API echoue et use_fallback=True, bascule sur le CSV local.
    """
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Appel API (tentative {attempt}/{retries})")
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()

            data = response.json()

            if isinstance(data, dict):
                transactions = data.get("data", data.get("transactions", []))
            elif isinstance(data, list):
                transactions = data
            else:
                logger.warning(f"Format de reponse inattendu: {type(data)}")
                transactions = []

            logger.info(f"{len(transactions)} transactions recuperees depuis l API")
            return transactions

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout (tentative {attempt}/{retries})")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Erreur de connexion (tentative {attempt}/{retries})")
        except requests.exceptions.HTTPError as e:
            logger.error(f"Erreur HTTP {e.response.status_code}: {e}")
            if e.response.status_code < 500:
                break
        except ValueError as e:
            logger.error(f"Erreur parsing JSON: {e}")
            break

        if attempt < retries:
            wait = 2 ** attempt
            logger.info(f"Retry dans {wait}s...")
            time.sleep(wait)

    # API inaccessible, on bascule sur le fallback si active
    if use_fallback:
        logger.warning(f"API inaccessible apres {retries} tentatives, activation du fallback CSV")
        return _fallback_from_csv(n=random.randint(1, 3))

    logger.error(f"Echec apres {retries} tentatives, pas de fallback")
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    txns = fetch_current_transactions()
    if txns:
        import json
        print(f"\nExemple :")
        print(json.dumps(txns[0] if txns else {}, indent=2, default=str))
