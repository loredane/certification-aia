#!/usr/bin/env python3
"""
Transaction generator — pousse du trafic dans PostgreSQL OLTP et appelle le ML service.
Usage : python scripts/transaction-generator.py --rate 10 --duration 600
"""
import argparse
import os
import random
import time
import uuid
from datetime import datetime, timezone

import psycopg2
import requests

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "SGD"]
DEVICES = ["mobile", "desktop", "tablet", "api"]
COUNTRIES = ["US", "FR", "GB", "DE", "CA", "JP", "AU", "SG", "NG", "RU"]


def get_conn():
    import os
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", 5432)),
        dbname=os.environ.get("POSTGRES_DB", "stripe_oltp"),
        user=os.environ.get("POSTGRES_USER", "stripe_app"),
        password=os.environ.get("POSTGRES_PASSWORD", "change_me"),
    )


def load_refs(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT customer_id FROM core.customers LIMIT 100")
        customers = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT merchant_id FROM core.merchants LIMIT 50")
        merchants = [r[0] for r in cur.fetchall()]
    return customers, merchants


def ensure_payment_methods(conn, customers):
    """Crée une carte par client si inexistante."""
    with conn.cursor() as cur:
        for cid in customers:
            cur.execute("SELECT 1 FROM core.payment_methods WHERE customer_id = %s", (cid,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO core.payment_methods
                        (customer_id, type, card_brand, last4, exp_month, exp_year,
                         token, fingerprint, is_default)
                    VALUES (%s, 'card', %s, %s, %s, %s, %s, %s, TRUE)
                """, (
                    cid,
                    random.choice(["visa", "mastercard", "amex"]),
                    f"{random.randint(1000,9999)}",
                    random.randint(1, 12),
                    random.randint(2027, 2031),
                    f"tok_{uuid.uuid4().hex[:16]}",
                    uuid.uuid4().hex,
                ))
        conn.commit()


def generate_transaction(conn, ml_url, customers, merchants):
    customer_id = random.choice(customers)
    merchant_id = random.choice(merchants)

    with conn.cursor() as cur:
        cur.execute("SELECT payment_method_id FROM core.payment_methods WHERE customer_id = %s LIMIT 1", (customer_id,))
        row = cur.fetchone()
        if not row:
            return
        pm_id = row[0]

    amount = round(random.lognormvariate(4, 1.5), 2)
    currency = random.choices(CURRENCIES, weights=[50, 25, 10, 5, 3, 3, 2, 2])[0]
    amount_usd = amount if currency == "USD" else round(amount * random.uniform(0.6, 1.3), 2)
    status = random.choices(
        ["captured", "pending", "failed", "authorized"],
        weights=[85, 5, 7, 3]
    )[0]
    device = random.choice(DEVICES)
    ip_country = random.choices(COUNTRIES, weights=[40, 15, 10, 8, 6, 6, 5, 5, 3, 2])[0]
    fraud_risk = random.random() * (1.5 if ip_country in {"NG", "RU"} else 0.6)
    fraud_score = min(1.0, fraud_risk)

    tx_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO core.transactions
                (transaction_id, merchant_id, customer_id, payment_method_id,
                 amount, currency_code, amount_usd, status, device_type,
                 fraud_score, is_3d_secure, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            tx_id, merchant_id, customer_id, pm_id,
            amount, currency, amount_usd, status, device,
            fraud_score, random.random() > 0.7, datetime.now(timezone.utc)
        ))
        conn.commit()

    # Appel ML service
    try:
        headers = {}
        api_keys = os.environ.get("ML_API_KEYS", "")
        if api_keys:
            headers["X-API-Key"] = api_keys.split(",")[0].strip()
        resp = requests.post(f"{ml_url}/score", json={
            "transaction_id": tx_id,
            "customer_id": str(customer_id),
            "merchant_id": str(merchant_id),
            "amount_usd": float(amount_usd),
            "currency_code": currency,
            "device_type": device,
            "ip_country": ip_country,
        }, headers=headers, timeout=2)
        if resp.ok:
            data = resp.json()
            print(f"  tx={tx_id[:8]} {amount_usd:>9.2f} {currency} "
                  f"status={status:<10} fraud={data['score']:.2f} decision={data['decision']}")
    except Exception as e:
        print(f"  tx={tx_id[:8]} ML call failed: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, default=2.0, help="Transactions par seconde")
    parser.add_argument("--duration", type=int, default=60, help="Durée en secondes")
    parser.add_argument("--ml-url", default="http://localhost:8001", help="ML service URL (8001 externally, see docker-compose)")
    args = parser.parse_args()

    conn = get_conn()
    customers, merchants = load_refs(conn)
    if not customers or not merchants:
        print("Pas de customers/merchants seed. Vérifier seed.sql.")
        return
    ensure_payment_methods(conn, customers)
    print(f"Génération : {args.rate} tx/s pendant {args.duration}s")
    print(f"Customers : {len(customers)} | Merchants : {len(merchants)}")

    end = time.time() + args.duration
    interval = 1.0 / args.rate
    count = 0
    while time.time() < end:
        generate_transaction(conn, args.ml_url, customers, merchants)
        count += 1
        time.sleep(interval)
    conn.close()
    print(f"\nTerminé. {count} transactions générées.")


if __name__ == "__main__":
    main()
