#!/usr/bin/env bash
# =============================================================================
# Kafka topics initialization for Stripe streaming
# DAMA-DMBOK2 ch.8 §1.3.10 — Event-based integration
# =============================================================================

set -euo pipefail

BROKER="${KAFKA_BROKER:-localhost:9092}"

echo "Creating Kafka topics on ${BROKER}..."

create_topic() {
    local name="$1" partitions="$2" retention_ms="$3"
    docker compose exec -T kafka kafka-topics --bootstrap-server kafka:29092 \
        --create --if-not-exists \
        --topic "$name" \
        --partitions "$partitions" \
        --replication-factor 1 \
        --config "retention.ms=$retention_ms" \
        --config "compression.type=zstd"
    echo "  ✓ $name (partitions=$partitions, retention=$(($retention_ms/86400000))d)"
}

# CDC topics (7 days retention)
create_topic "cdc.transactions"    12 604800000
create_topic "cdc.customers"        6 604800000
create_topic "cdc.payment_methods"  6 604800000
create_topic "cdc.disputes"         3 604800000

# Application events
create_topic "events.clickstream"  12 86400000      # 1 day (high volume)
create_topic "events.fraud_scored"  6 2592000000    # 30 days (audit)
create_topic "events.ml_predictions" 6 2592000000

# DLQ
create_topic "dlq.errors"           3 2592000000

echo ""
echo "Topics created. List:"
docker compose exec -T kafka kafka-topics --bootstrap-server kafka:29092 --list
