"""
Client pour récupérer les paiements depuis l'API temps réel.
L'API renvoie les transactions en cours, mise à jour chaque minute.
"""
import requests
import time
import logging

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import API_URL, API_TIMEOUT, API_RETRIES

logger = logging.getLogger(__name__)


def fetch_current_transactions(url=API_URL, timeout=API_TIMEOUT, retries=API_RETRIES):
    """
    Appelle l'API et retourne la liste des transactions.
    Retry avec backoff exponentiel si ça échoue.
    """
    for attempt in range(1, retries + 1):
        try:
            logger.info(f"Appel API (tentative {attempt}/{retries})")
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()

            data = response.json()

            # L'API peut renvoyer soit un dict soit une liste directement
            if isinstance(data, dict):
                transactions = data.get("data", data.get("transactions", []))
            elif isinstance(data, list):
                transactions = data
            else:
                logger.warning(f"Format de réponse inattendu: {type(data)}")
                transactions = []

            logger.info(f"{len(transactions)} transactions récupérées")
            return transactions

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout (tentative {attempt}/{retries})")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Erreur de connexion (tentative {attempt}/{retries})")
        except requests.exceptions.HTTPError as e:
            logger.error(f"Erreur HTTP {e.response.status_code}: {e}")
            # On retry que pour les erreurs serveur
            if e.response.status_code < 500:
                return None
        except ValueError as e:
            logger.error(f"Erreur parsing JSON: {e}")
            return None

        # Backoff exponentiel
        if attempt < retries:
            wait = 2 ** attempt
            logger.info(f"Retry dans {wait}s...")
            time.sleep(wait)

    logger.error(f"Echec après {retries} tentatives")
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    txns = fetch_current_transactions()
    if txns:
        import json
        print(f"\nExemple :")
        print(json.dumps(txns[0] if txns else {}, indent=2))
