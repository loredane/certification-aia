// =============================================================================
// Question business : Funnel de conversion checkout sur les 7 derniers jours.
// Combien de sessions passent par page_view -> checkout_start ->
// checkout_complete, vs checkout_abandon ? Decoupe par type d'appareil.
// (Cas d'usage : product team, optimisation UX checkout)
//
// Usage : mongosh "mongodb://stripe_app:$MONGO_APP_PASSWORD@localhost:27017/stripe_nosql" clickstream_funnel.js
// =============================================================================

db = db.getSiblingDB("stripe_nosql");

const since = new Date(Date.now() - 7 * 24 * 3600 * 1000);

const pipeline = [
    { $match: { timestamp: { $gte: since } } },

    // Regrouper les events par session pour savoir quels steps ont ete atteints
    {
        $group: {
            _id: {
                session_id: "$session_id",
                device_type: { $ifNull: ["$device.type", "unknown"] }
            },
            events: { $addToSet: "$event_type" }
        }
    },

    // Flags booleens par step
    {
        $project: {
            session_id:  "$_id.session_id",
            device_type: "$_id.device_type",
            has_page_view:         { $in: ["page_view",         "$events"] },
            has_checkout_start:    { $in: ["checkout_start",    "$events"] },
            has_checkout_complete: { $in: ["checkout_complete", "$events"] },
            has_checkout_abandon:  { $in: ["checkout_abandon",  "$events"] }
        }
    },

    // Agregation finale par device_type
    {
        $group: {
            _id: "$device_type",
            sessions:           { $sum: 1 },
            viewed:             { $sum: { $cond: ["$has_page_view", 1, 0] } },
            started_checkout:   { $sum: { $cond: ["$has_checkout_start", 1, 0] } },
            completed:          { $sum: { $cond: ["$has_checkout_complete", 1, 0] } },
            abandoned:          { $sum: { $cond: ["$has_checkout_abandon", 1, 0] } }
        }
    },

    // Taux de conversion
    {
        $project: {
            device_type: "$_id",
            _id: 0,
            sessions: 1,
            viewed: 1,
            started_checkout: 1,
            completed: 1,
            abandoned: 1,
            start_rate_pct: {
                $round: [{ $multiply: [{ $divide: ["$started_checkout", { $max: ["$viewed", 1] }] }, 100] }, 2]
            },
            completion_rate_pct: {
                $round: [{ $multiply: [{ $divide: ["$completed", { $max: ["$started_checkout", 1] }] }, 100] }, 2]
            }
        }
    },
    { $sort: { sessions: -1 } }
];

printjson(db.clickstream_events.aggregate(pipeline).toArray());
