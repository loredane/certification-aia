#!/usr/bin/env bash
# =============================================================================
# Script demo end-to-end pour la capture vidéo du pipeline
# Ordre optimal pour une démo de 2-3 min :
#  1) Stack up
#  2) Init CDC
#  3) Génération de transactions
#  4) Observation dans Kafka UI, Airflow, Grafana, ClickHouse, MongoDB
# =============================================================================
set -e

BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

echo -e "${BOLD}=== Stripe Data Architecture — Demo Pipeline ===${NC}"
echo ""

# 1. Stack up
echo -e "${YELLOW}[1/6]${NC} Démarrage de la stack Docker..."
docker-compose up -d
echo "   Services : PostgreSQL, Kafka, Debezium, ClickHouse, MongoDB, Airflow, dbt, Prometheus, Grafana"
sleep 10

# 2. Healthcheck
echo ""
echo -e "${YELLOW}[2/6]${NC} Attente readiness..."
until docker-compose exec -T postgres pg_isready -U stripe > /dev/null 2>&1; do
  echo "   Attente PostgreSQL..."; sleep 2
done
until docker-compose exec -T kafka kafka-topics --bootstrap-server localhost:29092 --list > /dev/null 2>&1; do
  echo "   Attente Kafka..."; sleep 2
done
echo -e "${GREEN}   ✓ Stack ready${NC}"

# 3. CDC Debezium
echo ""
echo -e "${YELLOW}[3/6]${NC} Activation du connecteur Debezium CDC..."
bash scripts/init-debezium.sh

# 4. Génération de transactions (déclenche CDC automatiquement)
echo ""
echo -e "${YELLOW}[4/6]${NC} Génération de 500 transactions de démo..."
docker-compose run --rm generator python generate.py --count 500

# 5. Vérification Kafka (CDC events)
echo ""
echo -e "${YELLOW}[5/6]${NC} Vérification des events CDC dans Kafka..."
docker-compose exec -T kafka kafka-console-consumer \
    --bootstrap-server localhost:29092 \
    --topic stripe.core.transaction \
    --from-beginning \
    --max-messages 3 \
    --timeout-ms 5000 2>/dev/null | head -3 || true

# 6. Points d'observation
echo ""
echo -e "${YELLOW}[6/6]${NC} ${BOLD}Démo prête pour la capture vidéo${NC}"
echo ""
echo "   Ouvre maintenant dans le navigateur pour filmer :"
echo "   ┌─────────────────────────────────────────────────────────┐"
echo "   │ Kafka UI        : http://localhost:8081                 │"
echo "   │ Airflow         : http://localhost:8080 (airflow/airflow) │"
echo "   │ Grafana         : http://localhost:3000 (admin/admin)   │"
echo "   │ Prometheus      : http://localhost:9090                 │"
echo "   │ ClickHouse HTTP : http://localhost:8123                 │"
echo "   └─────────────────────────────────────────────────────────┘"
echo ""
echo "   Requêtes à lancer pendant la capture vidéo :"
echo ""
echo "   ClickHouse OLAP :"
echo "   ────────────────"
echo "   docker-compose exec clickhouse clickhouse-client -q \\"
echo "     \"SELECT toDate(created_at) AS day, count(), sum(amount_eur) "
echo "      FROM stripe_olap.fact_transaction GROUP BY day ORDER BY day DESC LIMIT 10\""
echo ""
echo "   MongoDB NoSQL :"
echo "   ──────────────"
echo "   docker-compose exec mongodb mongosh stripe_nosql --quiet --eval \\"
echo "     \"db.ml_feature_store.countDocuments({})\""
echo ""
echo -e "${GREEN}✓ Demo pipeline terminée.${NC}"
