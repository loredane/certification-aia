"""
Validation des données dans le pipeline.

On vérifie la qualité à l'entrée (données de l'API) et à la sortie
(prédictions du modèle). Les transactions invalides sont envoyées
dans la dead letter queue pour ne pas bloquer le pipeline.

Ref: DAMA-DMBOK2 ch.13 (Data Quality Management)
"""
import logging
import json
from datetime import datetime
import psycopg2

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import DB_CONFIG, MAX_NULL_RATIO
from src.database.queries import INSERT_DQ_LOG, INSERT_DEAD_LETTER

logger = logging.getLogger(__name__)


class DataQualityValidator:
    """Checks de qualité sur les transactions : schéma, règles métier, prédictions."""

    def __init__(self):
        self.results = []

    def validate_schema(self, transaction):
        """Vérifie que les champs obligatoires sont présents et non null."""
        errors = []
        required = ["trans_num", "amt", "cc_num", "merchant", "category"]

        for field in required:
            if field not in transaction or transaction[field] is None:
                errors.append(f"Champ manquant ou null: {field}")

        is_valid = len(errors) == 0
        self._log_check("schema_validation", "schema", is_valid, errors)
        return is_valid, errors

    def validate_business_rules(self, transaction):
        """Règles métier : montant positif, coordonnées valides, numéro de carte valide."""
        errors = []

        # Montant positif et raisonnable
        amt = transaction.get("amt")
        if amt is not None:
            try:
                amt_val = float(amt)
                if amt_val <= 0:
                    errors.append(f"Montant <= 0: {amt}")
                if amt_val > 50000:
                    errors.append(f"Montant suspect (> 50k): {amt}")
            except (ValueError, TypeError):
                errors.append(f"Montant non numérique: {amt}")

        # Coordonnées GPS dans les bornes valides
        coord_checks = [
            ("lat", -90, 90), ("long", -180, 180),
            ("merch_lat", -90, 90), ("merch_long", -180, 180)
        ]
        for field, min_v, max_v in coord_checks:
            val = transaction.get(field)
            if val is not None:
                try:
                    v = float(val)
                    if not (min_v <= v <= max_v):
                        errors.append(f"{field} hors limites: {val}")
                except (ValueError, TypeError):
                    errors.append(f"{field} non numérique: {val}")

        # Numéro de carte valide (au moins 13 chiffres)
        cc = transaction.get("cc_num")
        if cc is not None and len(str(cc)) < 13:
            errors.append(f"N° carte trop court: {cc}")

        is_valid = len(errors) == 0
        self._log_check("business_rules", "rule", is_valid, errors)
        return is_valid, errors

    def validate_transaction(self, transaction):
        """Lance tous les checks sur une transaction."""
        all_errors = []

        ok1, errs1 = self.validate_schema(transaction)
        all_errors.extend(errs1)

        ok2, errs2 = self.validate_business_rules(transaction)
        all_errors.extend(errs2)

        is_valid = ok1 and ok2
        if not is_valid:
            logger.warning(f"Transaction {transaction.get('trans_num', '?')} rejetée: {all_errors}")

        return is_valid, all_errors

    def validate_prediction(self, probability):
        """Vérifie que la probabilité de fraude est dans [0, 1]."""
        errors = []
        if probability is None:
            errors.append("Probabilité null")
        elif not (0.0 <= probability <= 1.0):
            errors.append(f"Probabilité hors [0,1]: {probability}")

        is_valid = len(errors) == 0
        self._log_check("prediction_validation", "output", is_valid, errors)
        return is_valid, errors

    def _log_check(self, name, check_type, passed, errors):
        self.results.append({
            "check_name": name,
            "check_type": check_type,
            "passed": passed,
            "errors": errors,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def save_results_to_db(self, conn=None):
        """Persiste les résultats des checks dans data_quality_logs."""
        should_close = False
        if conn is None:
            conn = psycopg2.connect(**DB_CONFIG)
            should_close = True

        cur = conn.cursor()
        for r in self.results:
            cur.execute(INSERT_DQ_LOG, {
                "check_name": r["check_name"],
                "check_type": r["check_type"],
                "passed": r["passed"],
                "details": json.dumps({"errors": r["errors"]}),
                "records_checked": 1,
                "records_passed": 1 if r["passed"] else 0,
                "pass_rate": 1.0 if r["passed"] else 0.0,
            })
        conn.commit()
        cur.close()
        if should_close:
            conn.close()

        logger.info(f"{len(self.results)} checks DQ sauvegardés")
        self.results = []


def send_to_dead_letter_queue(transaction, error_type, error_message, source="api"):
    """Envoie une transaction rejetée dans la dead letter queue pour analyse ultérieure."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(INSERT_DEAD_LETTER, {
            "raw_data": json.dumps(transaction, default=str),
            "error_type": error_type,
            "error_message": error_message,
            "source": source,
        })
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Erreur DLQ: {e}")
