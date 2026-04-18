"""
Générateur de transactions réalistes pour la démo.
Injecte des customers, payment_methods et transactions dans PostgreSQL OLTP.
Les insertions déclenchent automatiquement le CDC Debezium → Kafka.
"""
import argparse
import os
import random
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg2
from psycopg2.extras import execute_values
from faker import Faker

fake = Faker()

# Distribution réaliste
CURRENCIES = [("EUR", 0.35), ("USD", 0.40), ("GBP", 0.10), ("JPY", 0.08),
              ("CAD", 0.04), ("BRL", 0.02), ("SGD", 0.01)]
STATUSES = [("succeeded", 0.88), ("failed", 0.08), ("pending", 0.03), ("refunded", 0.01)]
BRANDS = ["visa", "mastercard", "amex", "discover"]
PAYMENT_TYPE_CODES = ["card", "card", "card", "sepa", "wallet", "bnpl"]  # Card dominant


def weighted_choice(choices):
    total = sum(w for _, w in choices)
    r = random.uniform(0, total)
    upto = 0
    for val, w in choices:
        upto += w
        if upto >= r:
            return val
    return choices[-1][0]


def get_conn():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        dbname=os.getenv("POSTGRES_DB", "stripe_oltp"),
        user=os.getenv("POSTGRES_USER", "stripe"),
        password=os.getenv("POSTGRES_PASSWORD", "stripe_pwd"),
        port=5432,
    )


def fetch_reference(conn):
    """Récupère les données référentielles nécessaires."""
    with conn.cursor() as cur:
        cur.execute("SELECT country_code FROM reference.country")
        countries = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT payment_method_type_id, type_code FROM reference.payment_method_type")
        payment_types = {r[1]: r[0] for r in cur.fetchall()}

        cur.execute("SELECT customer_id FROM core.customer WHERE is_deleted = FALSE")
        customers = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT merchant_id FROM core.merchant WHERE kyc_status = 'verified'")
        merchants = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT payment_method_id, customer_id FROM core.payment_method")
        payment_methods = [(r[0], r[1]) for r in cur.fetchall()]
    return countries, payment_types, customers, merchants, payment_methods


def ensure_minimum_data(conn, countries, payment_types, customers, merchants, payment_methods,
                       min_customers=50, min_merchants=20):
    """Crée des customers / merchants / payment_methods si pas assez."""
    with conn.cursor() as cur:
        # Customers
        to_create = max(0, min_customers - len(customers))
        if to_create > 0:
            rows = [(
                fake.unique.email(),
                fake.first_name(),
                fake.last_name(),
                random.choice(countries),
            ) for _ in range(to_create)]
            execute_values(
                cur,
                "INSERT INTO core.customer (email, first_name, last_name, country_code) VALUES %s "
                "RETURNING customer_id",
                rows,
            )
            new_ids = [r[0] for r in cur.fetchall()]
            customers.extend(new_ids)
            print(f"  + {to_create} customers créés")

        # Merchants
        to_create = max(0, min_merchants - len(merchants))
        if to_create > 0:
            rows = [(
                fake.company(),
                random.choice(["5812", "5999", "7372", "5968", "4722", "5411", "5942"]),
                random.choice(countries),
                "verified",
            ) for _ in range(to_create)]
            execute_values(
                cur,
                "INSERT INTO core.merchant (business_name, mcc_code, country_code, kyc_status) VALUES %s "
                "RETURNING merchant_id",
                rows,
            )
            new_ids = [r[0] for r in cur.fetchall()]
            merchants.extend(new_ids)
            print(f"  + {to_create} merchants créés")

        # Payment methods : assure au moins 1 PM par customer
        customers_with_pm = {pm[1] for pm in payment_methods}
        customers_needing_pm = [c for c in customers if c not in customers_with_pm]
        if customers_needing_pm:
            rows = []
            for cid in customers_needing_pm:
                rows.append((
                    cid,
                    payment_types[random.choice(PAYMENT_TYPE_CODES)],
                    f"tok_{uuid4().hex}",
                    f"{random.randint(1000, 9999)}"[-4:],
                    random.choice(BRANDS),
                    random.randint(1, 12),
                    random.randint(2026, 2030),
                    True,
                ))
            execute_values(
                cur,
                "INSERT INTO core.payment_method "
                "(customer_id, payment_method_type_id, token, last4, brand, exp_month, exp_year, is_default) "
                "VALUES %s RETURNING payment_method_id, customer_id",
                rows,
            )
            new_pms = cur.fetchall()
            payment_methods.extend([(r[0], r[1]) for r in new_pms])
            print(f"  + {len(new_pms)} payment_methods créés")

        conn.commit()


def generate_transactions(conn, count, customers, merchants, payment_methods):
    """Génère N transactions étalées sur les 30 derniers jours."""
    pm_by_customer = {}
    for pm_id, c_id in payment_methods:
        pm_by_customer.setdefault(c_id, []).append(pm_id)

    now = datetime.utcnow()
    rows = []
    fraud_patterns = 0  # Injecte ~5% de transactions "suspectes" pour la démo fraude

    for _ in range(count):
        customer_id = random.choice(customers)
        pms = pm_by_customer.get(customer_id, [])
        if not pms:
            continue
        payment_method_id = random.choice(pms)
        merchant_id = random.choice(merchants)

        # Montant (distribution log-normale réaliste)
        amount_minor = int(max(50, random.lognormvariate(4.0, 1.3) * 100))
        currency = weighted_choice(CURRENCIES)
        if currency == "JPY":  # JPY n'a pas de décimales
            amount_minor = amount_minor * 100

        # Fraud score : 95% legit (0-0.4), 5% suspect (0.7-1.0)
        if random.random() < 0.05:
            fraud_score = round(random.uniform(0.7, 1.0), 3)
            fraud_patterns += 1
        else:
            fraud_score = round(random.uniform(0.0, 0.4), 3)

        fraud_decision = "decline" if fraud_score > 0.9 else ("review" if fraud_score > 0.7 else "approve")
        status = "failed" if fraud_decision == "decline" else weighted_choice(STATUSES)

        created_at = now - timedelta(
            days=random.randint(0, 30),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        rows.append((
            str(uuid4()),
            merchant_id,
            customer_id,
            payment_method_id,
            amount_minor,
            currency,
            status,
            fraud_score,
            fraud_decision,
            created_at,
        ))

    with conn.cursor() as cur:
        execute_values(
            cur,
            """INSERT INTO core.transaction
               (transaction_id, merchant_id, customer_id, payment_method_id,
                amount_minor, currency_code, status, fraud_score, fraud_decision, created_at)
               VALUES %s""",
            rows,
            page_size=500,
        )
        conn.commit()

    print(f"✓ {len(rows)} transactions insérées ({fraud_patterns} avec fraud_score > 0.7)")


def main():
    parser = argparse.ArgumentParser(description="Générateur de transactions Stripe")
    parser.add_argument("--count", type=int, default=500, help="Nombre de transactions à générer")
    args = parser.parse_args()

    print(f"[{datetime.utcnow().isoformat()}] Génération de {args.count} transactions...")
    conn = get_conn()
    try:
        countries, payment_types, customers, merchants, payment_methods = fetch_reference(conn)
        print(f"  Référentiel : {len(countries)} pays, {len(customers)} customers, "
              f"{len(merchants)} merchants, {len(payment_methods)} PM")
        ensure_minimum_data(conn, countries, payment_types, customers, merchants, payment_methods)
        generate_transactions(conn, args.count, customers, merchants, payment_methods)
    finally:
        conn.close()
    print("✓ Terminé.")


if __name__ == "__main__":
    main()
