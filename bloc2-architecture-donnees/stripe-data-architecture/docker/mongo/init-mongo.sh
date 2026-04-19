#!/usr/bin/env bash
# =============================================================================
# MongoDB initialization — executed automatically at first startup of the
# container (scripts placed in /docker-entrypoint-initdb.d/ are run by the
# official mongo image).
#
# FIX v3-mediums #5 : le password du user applicatif 'stripe_app' est
# désormais injecté via la variable d'environnement MONGO_APP_PASSWORD
# (plus de hardcode 'change_me_mongo_app' dans un .js committé).
#
# DAMA-DMBOK2 ch.5 §2.1.5 — NoSQL data modeling
# DAMA-DMBOK2 ch.6 §1.3.8 — Document databases
# DAMA-DMBOK2 ch.7 §1.3.3 — Password management
# =============================================================================
set -euo pipefail

: "${MONGO_INITDB_DATABASE:=stripe_nosql}"
: "${MONGO_APP_USER:=stripe_app}"

if [[ -z "${MONGO_APP_PASSWORD:-}" ]]; then
    echo "ERROR: MONGO_APP_PASSWORD env var must be set (see .env.example)" >&2
    exit 1
fi

echo "[init-mongo] creating application user '${MONGO_APP_USER}' on db '${MONGO_INITDB_DATABASE}'..."

# mongosh est fourni par l'image mongo:7. On exécute tout le script JS via
# --eval en interpolant le password depuis l'environnement shell (pas
# d'écriture du secret sur le disque).
mongosh \
    --quiet \
    --username "${MONGO_INITDB_ROOT_USERNAME}" \
    --password "${MONGO_INITDB_ROOT_PASSWORD}" \
    --authenticationDatabase admin \
    "${MONGO_INITDB_DATABASE}" \
    --eval "
    const dbName = '${MONGO_INITDB_DATABASE}';
    db = db.getSiblingDB(dbName);

    // ---- Application user (password from env, not from source) -----------
    const existing = db.getUser('${MONGO_APP_USER}');
    if (!existing) {
        db.createUser({
            user: '${MONGO_APP_USER}',
            pwd: '${MONGO_APP_PASSWORD}',
            roles: [{ role: 'readWrite', db: dbName }]
        });
        print('[init-mongo] user created');
    } else {
        db.changeUserPassword('${MONGO_APP_USER}', '${MONGO_APP_PASSWORD}');
        print('[init-mongo] user existed, password rotated');
    }

    // ---- Collections & schemas ------------------------------------------
    db.createCollection('clickstream_events', {
        validator: {
            \$jsonSchema: {
                bsonType: 'object',
                required: ['event_type', 'session_id', 'timestamp'],
                properties: {
                    event_type: {
                        bsonType: 'string',
                        enum: ['page_view', 'click', 'form_submit', 'checkout_start',
                               'checkout_complete', 'checkout_abandon', 'payment_method_select']
                    },
                    session_id: { bsonType: 'string' },
                    customer_id: { bsonType: ['string', 'null'] },
                    merchant_id: { bsonType: ['string', 'null'] },
                    page_url:    { bsonType: 'string' },
                    timestamp:   { bsonType: 'date' },
                    device: {
                        bsonType: 'object',
                        properties: {
                            type:    { bsonType: 'string' },
                            os:      { bsonType: 'string' },
                            browser: { bsonType: 'string' }
                        }
                    },
                    geo: {
                        bsonType: 'object',
                        properties: {
                            country: { bsonType: 'string' },
                            city:    { bsonType: 'string' },
                            ip_hash: { bsonType: 'string' }
                        }
                    }
                }
            }
        }
    });
    db.clickstream_events.createIndex({ session_id: 1, timestamp: 1 });
    db.clickstream_events.createIndex({ customer_id: 1, timestamp: -1 });
    db.clickstream_events.createIndex({ merchant_id: 1, timestamp: -1 });
    db.clickstream_events.createIndex({ timestamp: 1 }, { expireAfterSeconds: 7776000 }); // TTL 90j

    db.createCollection('ml_features_customer', {
        validator: {
            \$jsonSchema: {
                bsonType: 'object',
                required: ['customer_id', 'updated_at'],
                properties: {
                    customer_id: { bsonType: 'string' },
                    features: {
                        bsonType: 'object',
                        properties: {
                            tx_count_1h:            { bsonType: 'int' },
                            tx_count_24h:           { bsonType: 'int' },
                            tx_count_7d:            { bsonType: 'int' },
                            tx_amount_sum_24h:      { bsonType: 'double' },
                            tx_amount_avg_30d:      { bsonType: 'double' },
                            distinct_merchants_24h: { bsonType: 'int' },
                            distinct_countries_24h: { bsonType: 'int' },
                            velocity_score:         { bsonType: 'double' },
                            risk_score:             { bsonType: 'double' },
                            chargeback_ratio_90d:   { bsonType: 'double' }
                        }
                    },
                    updated_at:    { bsonType: 'date' },
                    model_version: { bsonType: 'string' }
                }
            }
        }
    });
    db.ml_features_customer.createIndex({ customer_id: 1 }, { unique: true });
    db.ml_features_customer.createIndex({ updated_at: -1 });

    db.createCollection('ml_features_merchant');
    db.ml_features_merchant.createIndex({ merchant_id: 1 }, { unique: true });

    db.createCollection('fraud_alerts', {
        validator: {
            \$jsonSchema: {
                bsonType: 'object',
                required: ['transaction_id', 'score', 'created_at'],
                properties: {
                    transaction_id:     { bsonType: 'string' },
                    customer_id:        { bsonType: 'string' },
                    merchant_id:        { bsonType: 'string' },
                    score:              { bsonType: 'double', minimum: 0, maximum: 1 },
                    decision:           { enum: ['approve', 'review', 'block'] },
                    model_version:      { bsonType: 'string' },
                    features_snapshot:  { bsonType: 'object' },
                    reasons:            { bsonType: 'array' },
                    created_at:         { bsonType: 'date' }
                }
            }
        }
    });
    db.fraud_alerts.createIndex({ transaction_id: 1 }, { unique: true });
    db.fraud_alerts.createIndex({ customer_id: 1, created_at: -1 });
    db.fraud_alerts.createIndex({ decision: 1, score: -1 });
    db.fraud_alerts.createIndex({ created_at: -1 });

    db.createCollection('customer_feedback');
    db.customer_feedback.createIndex({ customer_id: 1, created_at: -1 });
    db.customer_feedback.createIndex({ sentiment: 1 });
    db.customer_feedback.createIndex({ content: 'text' });

    db.createCollection('app_logs');
    db.app_logs.createIndex({ service: 1, level: 1, timestamp: -1 });
    db.app_logs.createIndex({ timestamp: 1 }, { expireAfterSeconds: 2592000 }); // TTL 30j

    // ---- ML model registry (ajouté par DAG ml_fraud_scoring) -------------
    db.createCollection('ml_model_registry');
    db.ml_model_registry.createIndex({ name: 1 }, { unique: true });

    print('[init-mongo] Collections ready: clickstream_events, ml_features_customer, ml_features_merchant, fraud_alerts, customer_feedback, app_logs, ml_model_registry');
"

echo "[init-mongo] done."
