#!/usr/bin/env bash
# =============================================================================
# Initialise le connecteur Debezium pour la CDC PostgreSQL → Kafka
# =============================================================================
set -e

DEBEZIUM_URL="${DEBEZIUM_URL:-http://localhost:8083}"
CONNECTOR_JSON="docker/debezium/connector.json"

echo "→ Attente que Debezium soit prêt..."
for i in {1..30}; do
  if curl -s "${DEBEZIUM_URL}/" > /dev/null 2>&1; then
    echo "✓ Debezium prêt"
    break
  fi
  echo "  ... attente (${i}/30)"
  sleep 2
done

# Supprimer le connecteur existant (idempotence)
curl -s -X DELETE "${DEBEZIUM_URL}/connectors/stripe-postgres-connector" > /dev/null 2>&1 || true

echo "→ Création du connecteur Debezium..."
curl -s -X POST "${DEBEZIUM_URL}/connectors" \
    -H "Content-Type: application/json" \
    -d @"${CONNECTOR_JSON}" | jq .

echo ""
echo "→ État du connecteur :"
sleep 2
curl -s "${DEBEZIUM_URL}/connectors/stripe-postgres-connector/status" | jq .

echo ""
echo "✓ CDC PostgreSQL → Kafka opérationnel"
echo "  Topics attendus : stripe.core.transaction, stripe.core.customer,"
echo "                    stripe.core.merchant, stripe.core.payment_method"
