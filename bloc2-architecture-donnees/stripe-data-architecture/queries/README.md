# Queries — Livrable Bloc 2 AIA

> **FIX v3-mediums #23** — Requetes de demonstration pour le jury.

## Organisation

```
queries/
├── snowflake/
│   ├── revenue_by_region.sql          -- Revenu net par region, 30j
│   ├── top_fraud_merchants.sql        -- Top 20 merchants a risque, 90j
│   ├── customer_cohort_retention.sql  -- Cohortes retention M+1/M+3/M+6
│   └── fraud_rate_by_mcc_country.sql  -- Cartographie fraude MCC x pays
├── postgres/
│   └── audit_log_review.sql           -- Revue PCI-DSS Req 10.6
└── mongodb/
    ├── clickstream_funnel.js          -- Funnel conversion checkout
    └── top_fraud_customers.js         -- Top 50 clients alertes
```

## Execution

### Snowflake
```bash
snowsql -a $SNOWFLAKE_ACCOUNT -u $SNOWFLAKE_USER \
        -r REPORTING_ROLE -w REPORTING \
        -f queries/snowflake/revenue_by_region.sql
```

### Postgres
```bash
psql "postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/stripe_oltp" \
     -f queries/postgres/audit_log_review.sql
```

### MongoDB
```bash
mongosh "mongodb://stripe_app:$MONGO_APP_PASSWORD@localhost:27017/stripe_nosql" \
        queries/mongodb/clickstream_funnel.js
```

## Mapping competences RNCP38777 Bloc 2

| Requete | Competence evaluee |
|---|---|
| `revenue_by_region.sql` | Concevoir des structures adaptees aux performances (OLAP star schema) |
| `top_fraud_merchants.sql` | Integration ML (utilise les scores produits par le DAG fraud) |
| `customer_cohort_retention.sql` | Modelisation dimensionnelle (dim_customer + fact grain tx) |
| `fraud_rate_by_mcc_country.sql` | Aggregation analytique sur star schema |
| `audit_log_review.sql` | Conformite PCI-DSS (audit, tracabilite) |
| `clickstream_funnel.js` | Modelisation NoSQL (schema flexible, aggregation pipeline) |
| `top_fraud_customers.js` | ML feature store + NoSQL indexation |
