// =============================================================================
// Livrable 8 — Requêtes MongoDB NoSQL
// Cas business : logs, clickstream, features ML, feedback, fraud alerts
// =============================================================================

use("stripe_nosql");

// -----------------------------------------------------------------------------
// Q1 — Logs d'erreur du service payment-api sur 1h (index compound)
// -----------------------------------------------------------------------------
db.event_logs.find(
  {
    service: "payment-api",
    level: { $in: ["ERROR", "CRITICAL"] },
    timestamp: { $gte: new Date(Date.now() - 3600 * 1000) }
  },
  { _id: 0, timestamp: 1, message: 1, trace_id: 1, context: 1 }
).sort({ timestamp: -1 }).limit(50);


// -----------------------------------------------------------------------------
// Q2 — Clickstream : funnel de conversion par pays (aggregation pipeline)
// -----------------------------------------------------------------------------
db.clickstream_sessions.aggregate([
  { $match: { started_at: { $gte: new Date(Date.now() - 7 * 24 * 3600 * 1000) } } },
  { $unwind: "$events" },
  {
    $group: {
      _id: { country: "$geo.country", event_type: "$events.event_type" },
      count: { $sum: 1 }
    }
  },
  {
    $group: {
      _id: "$_id.country",
      funnel: {
        $push: { event_type: "$_id.event_type", count: "$count" }
      },
      total_events: { $sum: "$count" }
    }
  },
  { $sort: { total_events: -1 } },
  { $limit: 10 }
]);


// -----------------------------------------------------------------------------
// Q3 — Feature store : récupération des features d'un customer (lookup temps réel)
// -----------------------------------------------------------------------------
db.ml_feature_store.findOne(
  { customer_id: "<CUSTOMER_UUID>" },
  {
    _id: 0,
    features_version: 1,
    computed_at: 1,
    "transaction_features.tx_count_30d": 1,
    "transaction_features.avg_amount_30d": 1,
    "transaction_features.distinct_countries_30d": 1,
    "transaction_features.failed_tx_rate_30d": 1,
    "risk_features.fraud_score_latest": 1
  }
);


// -----------------------------------------------------------------------------
// Q4 — Top 100 customers avec le plus haut fraud_score_latest
// -----------------------------------------------------------------------------
db.ml_feature_store.find(
  { "risk_features.fraud_score_latest": { $gt: 0.7 } },
  {
    customer_id: 1,
    "risk_features.fraud_score_latest": 1,
    "risk_features.chargeback_count_180d": 1,
    "transaction_features.distinct_countries_30d": 1
  }
).sort({ "risk_features.fraud_score_latest": -1 }).limit(100);


// -----------------------------------------------------------------------------
// Q5 — Full-text search sur customer_feedback (recherche "chargeback" OU "refund")
// -----------------------------------------------------------------------------
db.customer_feedback.find(
  { $text: { $search: "chargeback refund dispute" } },
  { score: { $meta: "textScore" }, subject: 1, body: 1, sentiment: 1, rating: 1 }
).sort({ score: { $meta: "textScore" } }).limit(20);


// -----------------------------------------------------------------------------
// Q6 — Sentiment mensuel : distribution positive / neutral / negative
// -----------------------------------------------------------------------------
db.customer_feedback.aggregate([
  { $match: { created_at: { $gte: new Date(Date.now() - 90 * 24 * 3600 * 1000) } } },
  {
    $group: {
      _id: {
        month: { $dateToString: { format: "%Y-%m", date: "$created_at" } },
        sentiment: "$sentiment"
      },
      count: { $sum: 1 },
      avg_rating: { $avg: "$rating" }
    }
  },
  { $sort: { "_id.month": -1, "_id.sentiment": 1 } }
]);


// -----------------------------------------------------------------------------
// Q7 — Fraud alerts time-series : moyenne horaire par pays (dernière 24h)
// -----------------------------------------------------------------------------
db.fraud_alerts.aggregate([
  { $match: { detected_at: { $gte: new Date(Date.now() - 24 * 3600 * 1000) } } },
  {
    $group: {
      _id: {
        hour: { $dateTrunc: { date: "$detected_at", unit: "hour" } },
        country: "$metadata.country_code",
        level: "$metadata.alert_level"
      },
      count: { $sum: 1 }
    }
  },
  { $sort: { "_id.hour": -1, count: -1 } },
  { $limit: 100 }
]);


// -----------------------------------------------------------------------------
// Q8 — Upsert d'une feature (appelé par le DAG horaire)
// -----------------------------------------------------------------------------
db.ml_feature_store.updateOne(
  { customer_id: "<CUSTOMER_UUID>" },
  {
    $set: {
      features_version: "v1.2",
      computed_at: new Date(),
      "transaction_features.tx_count_7d": 12,
      "transaction_features.avg_amount_7d": 45.80,
      "risk_features.fraud_score_latest": 0.15
    }
  },
  { upsert: true }
);
