// =============================================================================
// Question business : Top 50 clients avec le plus d'alertes fraud "block"
// ou "review" sur les 30 derniers jours, et leur score moyen.
// (Cas d'usage : list de revue manuelle risk team)
//
// Usage : mongosh "mongodb://stripe_app:$MONGO_APP_PASSWORD@localhost:27017/stripe_nosql" top_fraud_customers.js
// =============================================================================

db = db.getSiblingDB("stripe_nosql");

const since = new Date(Date.now() - 30 * 24 * 3600 * 1000);

const pipeline = [
    {
        $match: {
            created_at: { $gte: since },
            decision:   { $in: ["review", "block"] }
        }
    },
    {
        $group: {
            _id: "$customer_id",
            alerts_total:  { $sum: 1 },
            blocks:        { $sum: { $cond: [{ $eq: ["$decision", "block"] }, 1, 0] } },
            reviews:       { $sum: { $cond: [{ $eq: ["$decision", "review"] }, 1, 0] } },
            avg_score:     { $avg: "$score" },
            max_score:     { $max: "$score" },
            merchants_hit: { $addToSet: "$merchant_id" },
            last_alert:    { $max: "$created_at" }
        }
    },
    {
        $project: {
            customer_id:      "$_id",
            _id:              0,
            alerts_total:     1,
            blocks:           1,
            reviews:          1,
            avg_score:        { $round: ["$avg_score", 3] },
            max_score:        { $round: ["$max_score", 3] },
            merchants_touched: { $size: "$merchants_hit" },
            last_alert:       1
        }
    },
    { $sort: { alerts_total: -1, avg_score: -1 } },
    { $limit: 50 }
];

printjson(db.fraud_alerts.aggregate(pipeline).toArray());
