-- =============================================================================
-- Stripe OLAP Star Schema — ClickHouse 24
-- Modélisation dimensionnelle Kimball (DAMA-DMBOK2 ch.5 §1.3.5.5)
-- SCD Type 2 pour customer et merchant
-- Materialized Views pour pré-agrégations (DAMA ch.6 §2.3)
-- =============================================================================

CREATE DATABASE IF NOT EXISTS stripe_olap;
USE stripe_olap;

-- =============================================================================
-- DIM_DATE — Dimension temporelle (générée une fois)
-- =============================================================================
CREATE TABLE dim_date (
    date_id       UInt32,              -- format YYYYMMDD
    date_actual   Date,
    year          UInt16,
    quarter       UInt8,
    month         UInt8,
    month_name    LowCardinality(String),
    day           UInt8,
    day_of_week   UInt8,
    day_name      LowCardinality(String),
    is_weekend    UInt8,
    week_of_year  UInt8,
    is_holiday    UInt8 DEFAULT 0
) ENGINE = MergeTree()
ORDER BY (date_id);

-- Génération dim_date de 2020 à 2030
INSERT INTO dim_date
SELECT
    toYYYYMMDD(d)                              AS date_id,
    d                                          AS date_actual,
    toYear(d)                                  AS year,
    toQuarter(d)                               AS quarter,
    toMonth(d)                                 AS month,
    toString(toMonth(d))                       AS month_name,
    toDayOfMonth(d)                            AS day,
    toDayOfWeek(d)                             AS day_of_week,
    toString(toDayOfWeek(d))                   AS day_name,
    if(toDayOfWeek(d) >= 6, 1, 0)              AS is_weekend,
    toWeek(d)                                  AS week_of_year,
    0                                          AS is_holiday
FROM (SELECT addDays(toDate('2020-01-01'), number) AS d
      FROM numbers(toUInt32(toDate('2030-12-31') - toDate('2020-01-01')) + 1));

-- =============================================================================
-- DIM_CUSTOMER — SCD Type 2 (historique complet)
-- =============================================================================
CREATE TABLE dim_customer (
    customer_sk      UInt64,                -- Surrogate key
    customer_id      String,                -- Natural key (UUID OLTP)
    email_hashed     String,                -- Email hashé (GDPR)
    country_code     LowCardinality(String),
    region           LowCardinality(String),
    is_eu            UInt8,
    valid_from       DateTime,
    valid_to         DateTime DEFAULT toDateTime('9999-12-31 23:59:59'),
    is_current       UInt8,
    is_deleted       UInt8 DEFAULT 0
) ENGINE = ReplacingMergeTree(valid_from)
ORDER BY (customer_id, valid_from);

-- =============================================================================
-- DIM_MERCHANT — SCD Type 2
-- =============================================================================
CREATE TABLE dim_merchant (
    merchant_sk    UInt64,
    merchant_id    String,
    business_name  String,
    mcc_code       LowCardinality(String),
    country_code   LowCardinality(String),
    region         LowCardinality(String),
    kyc_status     LowCardinality(String),
    valid_from     DateTime,
    valid_to       DateTime DEFAULT toDateTime('9999-12-31 23:59:59'),
    is_current     UInt8
) ENGINE = ReplacingMergeTree(valid_from)
ORDER BY (merchant_id, valid_from);

-- =============================================================================
-- DIM_PAYMENT_METHOD
-- =============================================================================
CREATE TABLE dim_payment_method (
    payment_method_sk   UInt64,
    payment_method_id   String,
    type_code           LowCardinality(String),   -- card, sepa, ach, wallet...
    brand               LowCardinality(String),   -- visa, mastercard...
    country_issue       LowCardinality(String)
) ENGINE = ReplacingMergeTree()
ORDER BY (payment_method_id);

-- =============================================================================
-- DIM_CURRENCY
-- =============================================================================
CREATE TABLE dim_currency (
    currency_code   LowCardinality(String),
    currency_name   String,
    decimals        UInt8
) ENGINE = ReplacingMergeTree()
ORDER BY (currency_code);

-- =============================================================================
-- DIM_GEOGRAPHY
-- =============================================================================
CREATE TABLE dim_geography (
    geography_sk    UInt64,
    country_code    LowCardinality(String),
    country_name    String,
    region          LowCardinality(String),
    is_eu           UInt8
) ENGINE = ReplacingMergeTree()
ORDER BY (country_code);

-- =============================================================================
-- FACT_TRANSACTION — Grain : une ligne par transaction
-- =============================================================================
CREATE TABLE fact_transaction (
    transaction_id       String,
    date_id              UInt32,
    customer_sk          UInt64,
    merchant_sk          UInt64,
    payment_method_sk    UInt64,
    currency_code        LowCardinality(String),
    geography_sk         UInt64,
    amount_minor         Int64,                  -- Measures
    amount_eur           Float64,                 -- Converti en devise commune
    fee_minor            Int64,
    fraud_score          Float32,
    status               LowCardinality(String),
    created_at           DateTime,
    ingested_at          DateTime DEFAULT now()
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)                 -- Partition mensuelle
ORDER BY (date_id, merchant_sk, customer_sk)
TTL created_at + INTERVAL 7 YEAR                  -- Rétention conformité
SETTINGS index_granularity = 8192;

-- =============================================================================
-- MATERIALIZED VIEW — Revenue quotidien pré-agrégé
-- =============================================================================
CREATE TABLE fact_daily_revenue (
    date_id            UInt32,
    merchant_sk        UInt64,
    country_code       LowCardinality(String),
    currency_code      LowCardinality(String),
    transaction_count  UInt64,
    gross_revenue_eur  Float64,
    net_revenue_eur    Float64,
    success_rate       Float32,
    avg_fraud_score    Float32
) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(toDate(date_id))
ORDER BY (date_id, merchant_sk, country_code, currency_code);

CREATE MATERIALIZED VIEW mv_daily_revenue TO fact_daily_revenue AS
SELECT
    date_id,
    merchant_sk,
    dictGetOrDefault('dict_geography', 'country_code', geography_sk, '??') AS country_code,
    currency_code,
    count()                                                                AS transaction_count,
    sum(amount_eur)                                                        AS gross_revenue_eur,
    sum(amount_eur - fee_minor / 100.0)                                    AS net_revenue_eur,
    avgIf(1, status = 'succeeded')                                         AS success_rate,
    avg(fraud_score)                                                       AS avg_fraud_score
FROM fact_transaction
GROUP BY date_id, merchant_sk, geography_sk, currency_code;

-- =============================================================================
-- MATERIALIZED VIEW — Fraud analysis horaire
-- =============================================================================
CREATE TABLE fact_hourly_fraud (
    hour_ts           DateTime,
    country_code      LowCardinality(String),
    payment_type      LowCardinality(String),
    high_risk_count   UInt64,
    declined_count    UInt64,
    total_count       UInt64,
    fraud_rate        Float32
) ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour_ts)
ORDER BY (hour_ts, country_code, payment_type);

CREATE MATERIALIZED VIEW mv_hourly_fraud TO fact_hourly_fraud AS
SELECT
    toStartOfHour(created_at)                           AS hour_ts,
    dictGetOrDefault('dict_geography', 'country_code', geography_sk, '??') AS country_code,
    dictGetOrDefault('dict_payment', 'type_code', payment_method_sk, '??') AS payment_type,
    countIf(fraud_score > 0.7)                          AS high_risk_count,
    countIf(status = 'failed' AND fraud_score > 0.5)    AS declined_count,
    count()                                             AS total_count,
    high_risk_count / total_count                       AS fraud_rate
FROM fact_transaction
GROUP BY hour_ts, geography_sk, payment_method_sk;

-- =============================================================================
-- RBAC (DAMA ch.7 §1.3.4)
-- =============================================================================
CREATE USER analytics_reader IDENTIFIED WITH sha256_password BY 'analytics_pwd';
CREATE USER bi_tools IDENTIFIED WITH sha256_password BY 'bi_pwd';

CREATE ROLE read_only;
GRANT SELECT ON stripe_olap.* TO read_only;
GRANT read_only TO analytics_reader, bi_tools;

-- Rôle restreint (anonymisation GDPR) — pas d'accès aux tables dim_customer détaillées
CREATE ROLE read_only_anon;
GRANT SELECT ON stripe_olap.fact_daily_revenue TO read_only_anon;
GRANT SELECT ON stripe_olap.fact_hourly_fraud TO read_only_anon;
GRANT SELECT ON stripe_olap.dim_date TO read_only_anon;
GRANT SELECT ON stripe_olap.dim_merchant TO read_only_anon;
GRANT SELECT ON stripe_olap.dim_geography TO read_only_anon;
