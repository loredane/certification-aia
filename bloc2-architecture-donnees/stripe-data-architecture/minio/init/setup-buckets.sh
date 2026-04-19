#!/usr/bin/env bash
# =============================================================================
# MinIO buckets initialization — Medallion architecture
# Fundamentals of Data Engineering ch.8 — Lakehouse / Medallion
#
# FIX v3: ce script n'est plus nécessaire en usage normal.
# Le service `minio-init` dans docker-compose.yml s'en charge automatiquement
# au démarrage (sidecar one-shot basé sur l'image minio/mc).
#
# Ce script reste fourni uniquement pour :
#   - Re-créer les buckets manuellement après un reset partiel
#   - Déboguer l'initialisation MinIO
# =============================================================================

set -euo pipefail

MINIO_USER="${MINIO_USER:-minioadmin}"
MINIO_PASSWORD="${MINIO_PASSWORD:-minioadmin}"

echo "Initialisation MinIO via container sidecar minio/mc..."

# On lance mc dans un container dédié car l'image minio/minio ne contient
# pas le binaire mc. On se raccroche au réseau Docker Compose du projet.
PROJECT_NAME="$(basename "$(pwd)")"
NETWORK="${PROJECT_NAME}_stripe_net"

docker run --rm --network="${NETWORK}" \
  -e MINIO_USER="${MINIO_USER}" \
  -e MINIO_PASSWORD="${MINIO_PASSWORD}" \
  minio/mc:RELEASE.2024-11-21T17-21-54Z \
  sh -c '
    set -e
    mc alias set local http://minio:9000 "$MINIO_USER" "$MINIO_PASSWORD"

    # Bronze — raw data as-is from sources
    mc mb --ignore-existing local/stripe-raw

    # Silver — cleaned, validated, typed
    mc mb --ignore-existing local/stripe-staging

    # Gold — business-ready marts exports
    mc mb --ignore-existing local/stripe-marts

    # Archive — long-term, PCI-DSS 7y compliance
    mc mb --ignore-existing local/stripe-archive
    mc version enable local/stripe-archive || true

    # ML artifacts
    mc mb --ignore-existing local/ml-artifacts

    echo ""
    echo "Buckets présents :"
    mc ls local/
  '

echo "✓ MinIO buckets ready"
