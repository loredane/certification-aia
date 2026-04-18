// =============================================================================
// Stripe NoSQL Data Model — MongoDB 7
// Modèle document (DAMA-DMBOK2 ch.5 §1.3.6) : embedding vs referencing
// JSON Schema validation, index compound / full-text / sparse / TTL
// =============================================================================

db = db.getSiblingDB('stripe_nosql');

// =============================================================================
// COLLECTION 1 : event_logs (logs techniques + applicatifs)
// TTL 90 jours, index time-series
// =============================================================================
db.createCollection("event_logs", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["event_id", "service", "level", "timestamp", "message"],
      properties: {
        event_id:   { bsonType: "string" },
        service:    { bsonType: "string", description: "payment-api, fraud-engine..." },
        level:      { enum: ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"] },
        timestamp:  { bsonType: "date" },
        message:    { bsonType: "string" },
        context:    { bsonType: "object" },
        trace_id:   { bsonType: "string" },
        user_id:    { bsonType: "string" }
      }
    }
  }
});

db.event_logs.createIndex({ timestamp: -1 });
db.event_logs.createIndex({ service: 1, level: 1, timestamp: -1 });
db.event_logs.createIndex({ trace_id: 1 }, { sparse: true });
db.event_logs.createIndex({ timestamp: 1 }, { expireAfterSeconds: 7776000 }); // TTL 90j

// =============================================================================
// COLLECTION 2 : clickstream_sessions (navigation utilisateur)
// Embedding des événements dans le document session (cohésion forte)
// =============================================================================
db.createCollection("clickstream_sessions", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["session_id", "user_id", "started_at"],
      properties: {
        session_id:  { bsonType: "string" },
        user_id:     { bsonType: "string" },
        device:      {
          bsonType: "object",
          properties: {
            type:    { enum: ["mobile", "desktop", "tablet"] },
            os:      { bsonType: "string" },
            browser: { bsonType: "string" }
          }
        },
        geo:         {
          bsonType: "object",
          properties: {
            country: { bsonType: "string" },
            city:    { bsonType: "string" },
            coordinates: { bsonType: "array" }
          }
        },
        started_at:  { bsonType: "date" },
        ended_at:    { bsonType: "date" },
        events: {
          bsonType: "array",
          description: "Events embedded (pattern embedding : accès atomique à la session complète)",
          items: {
            bsonType: "object",
            properties: {
              event_type: { enum: ["page_view", "click", "add_to_cart", "checkout", "purchase"] },
              timestamp:  { bsonType: "date" },
              page_url:   { bsonType: "string" },
              properties: { bsonType: "object" }
            }
          }
        }
      }
    }
  }
});

db.clickstream_sessions.createIndex({ user_id: 1, started_at: -1 });
db.clickstream_sessions.createIndex({ "geo.country": 1 });
db.clickstream_sessions.createIndex({ started_at: 1 }, { expireAfterSeconds: 15552000 }); // TTL 180j

// =============================================================================
// COLLECTION 3 : ml_feature_store (features calculées pour les modèles ML)
// Pattern referencing (customer_id → OLTP)
// =============================================================================
db.createCollection("ml_feature_store", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["customer_id", "features_version", "computed_at"],
      properties: {
        customer_id: { bsonType: "string" },
        features_version: { bsonType: "string", description: "v1, v2.3..." },
        computed_at: { bsonType: "date" },
        // Features rolling window
        transaction_features: {
          bsonType: "object",
          properties: {
            tx_count_7d:        { bsonType: "int" },
            tx_count_30d:       { bsonType: "int" },
            avg_amount_7d:      { bsonType: "double" },
            avg_amount_30d:     { bsonType: "double" },
            distinct_countries_30d: { bsonType: "int" },
            distinct_merchants_30d: { bsonType: "int" },
            failed_tx_rate_30d: { bsonType: "double" }
          }
        },
        behavioral_features: {
          bsonType: "object",
          properties: {
            session_count_7d:     { bsonType: "int" },
            avg_session_duration: { bsonType: "double" },
            device_changes_30d:   { bsonType: "int" }
          }
        },
        risk_features: {
          bsonType: "object",
          properties: {
            chargeback_count_180d: { bsonType: "int" },
            disputes_count_180d:   { bsonType: "int" },
            fraud_score_latest:    { bsonType: "double" }
          }
        }
      }
    }
  }
});

db.ml_feature_store.createIndex({ customer_id: 1 }, { unique: true });
db.ml_feature_store.createIndex({ computed_at: -1 });
db.ml_feature_store.createIndex({ "risk_features.fraud_score_latest": -1 });

// =============================================================================
// COLLECTION 4 : customer_feedback (reviews + support tickets)
// Full-text search
// =============================================================================
db.createCollection("customer_feedback", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["feedback_id", "customer_id", "channel", "created_at"],
      properties: {
        feedback_id: { bsonType: "string" },
        customer_id: { bsonType: "string" },
        channel:     { enum: ["email", "chat", "nps", "app_review", "social"] },
        sentiment:   { enum: ["positive", "neutral", "negative"] },
        rating:      { bsonType: "int", minimum: 1, maximum: 5 },
        subject:     { bsonType: "string" },
        body:        { bsonType: "string" },
        tags:        { bsonType: "array", items: { bsonType: "string" } },
        created_at:  { bsonType: "date" }
      }
    }
  }
});

db.customer_feedback.createIndex({ customer_id: 1, created_at: -1 });
db.customer_feedback.createIndex({ sentiment: 1, created_at: -1 });
// Full-text index (DAMA ch.5 §1.3.6.4)
db.customer_feedback.createIndex(
  { subject: "text", body: "text" },
  { weights: { subject: 10, body: 5 }, name: "full_text_search" }
);

// =============================================================================
// COLLECTION 5 : fraud_alerts (alertes temps réel)
// Time-series collection (MongoDB 5+)
// =============================================================================
db.createCollection("fraud_alerts", {
  timeseries: {
    timeField: "detected_at",
    metaField: "metadata",
    granularity: "minutes"
  }
});

db.fraud_alerts.createIndex({ "metadata.customer_id": 1, detected_at: -1 });
db.fraud_alerts.createIndex({ "metadata.alert_level": 1, detected_at: -1 });

// =============================================================================
// RBAC (DAMA ch.7 §1.3.4)
// =============================================================================
db.createRole({
  role: "feature_store_reader",
  privileges: [
    { resource: { db: "stripe_nosql", collection: "ml_feature_store" }, actions: ["find"] }
  ],
  roles: []
});

db.createRole({
  role: "fraud_analyst",
  privileges: [
    { resource: { db: "stripe_nosql", collection: "fraud_alerts" }, actions: ["find", "insert"] },
    { resource: { db: "stripe_nosql", collection: "event_logs" }, actions: ["find"] }
  ],
  roles: []
});

db.createRole({
  role: "logs_reader",
  privileges: [
    { resource: { db: "stripe_nosql", collection: "event_logs" }, actions: ["find"] },
    { resource: { db: "stripe_nosql", collection: "clickstream_sessions" }, actions: ["find"] }
  ],
  roles: []
});

print("✓ stripe_nosql database initialized");
print("  - event_logs (TTL 90j + time-series indexes)");
print("  - clickstream_sessions (embedded events + TTL 180j)");
print("  - ml_feature_store (referencing customer_id)");
print("  - customer_feedback (full-text search)");
print("  - fraud_alerts (time-series collection)");
