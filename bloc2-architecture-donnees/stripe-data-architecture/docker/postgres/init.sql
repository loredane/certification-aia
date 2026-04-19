-- =============================================================================
-- Stripe OLTP — PostgreSQL 3NF Schema
-- DAMA-DMBOK2 ch.5 §1.3.3 — Relational Data Modeling (3NF normalization)
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Schemas
CREATE SCHEMA IF NOT EXISTS core;      -- Business domain
CREATE SCHEMA IF NOT EXISTS reference; -- Reference data
CREATE SCHEMA IF NOT EXISTS audit;     -- Audit logs (PCI-DSS)

-- =============================================================================
-- REFERENCE DATA (quasi-static)
-- =============================================================================

CREATE TABLE reference.countries (
    country_code    CHAR(2) PRIMARY KEY,
    country_name    VARCHAR(100) NOT NULL,
    region          VARCHAR(50) NOT NULL,
    is_high_risk    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE reference.currencies (
    currency_code   CHAR(3) PRIMARY KEY,
    currency_name   VARCHAR(50) NOT NULL,
    decimal_places  SMALLINT NOT NULL DEFAULT 2,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE reference.exchange_rates (
    rate_id         BIGSERIAL PRIMARY KEY,
    from_currency   CHAR(3) NOT NULL REFERENCES reference.currencies(currency_code),
    to_currency     CHAR(3) NOT NULL REFERENCES reference.currencies(currency_code),
    rate            NUMERIC(18,8) NOT NULL,
    effective_date  DATE NOT NULL,
    UNIQUE (from_currency, to_currency, effective_date)
);
CREATE INDEX idx_fx_effective ON reference.exchange_rates(effective_date);

CREATE TABLE reference.mcc_codes (
    mcc_code        VARCHAR(4) PRIMARY KEY,
    description     VARCHAR(200) NOT NULL,
    category        VARCHAR(100)
);

-- =============================================================================
-- CUSTOMERS
-- =============================================================================

CREATE TABLE core.customers (
    customer_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    email_hash      VARCHAR(64) NOT NULL,  -- SHA-256 for GDPR pseudonymization
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    phone_encrypted BYTEA,  -- AES-256 encrypted
    country_code    CHAR(2) REFERENCES reference.countries(country_code),
    kyc_status      VARCHAR(20) DEFAULT 'pending'
                     CHECK (kyc_status IN ('pending','verified','rejected','suspended')),
    risk_score      NUMERIC(5,4) DEFAULT 0.0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,  -- Soft delete for GDPR right to be forgotten
    CONSTRAINT risk_score_range CHECK (risk_score BETWEEN 0 AND 1)
);
CREATE INDEX idx_customers_email_hash ON core.customers(email_hash);
CREATE INDEX idx_customers_country ON core.customers(country_code);
CREATE INDEX idx_customers_created ON core.customers(created_at DESC);

-- =============================================================================
-- MERCHANTS
-- =============================================================================

CREATE TABLE core.merchants (
    merchant_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_name   VARCHAR(255) NOT NULL,
    business_type   VARCHAR(50) NOT NULL
                     CHECK (business_type IN ('company','individual','nonprofit','government')),
    mcc_code        VARCHAR(4) REFERENCES reference.mcc_codes(mcc_code),
    country_code    CHAR(2) REFERENCES reference.countries(country_code),
    status          VARCHAR(20) DEFAULT 'active'
                     CHECK (status IN ('active','suspended','terminated')),
    onboarded_at    TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_merchants_country ON core.merchants(country_code);
CREATE INDEX idx_merchants_mcc ON core.merchants(mcc_code);
CREATE INDEX idx_merchants_status ON core.merchants(status);

-- =============================================================================
-- PAYMENT METHODS (tokenized for PCI-DSS)
-- =============================================================================

CREATE TABLE core.payment_methods (
    payment_method_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id     UUID NOT NULL REFERENCES core.customers(customer_id) ON DELETE CASCADE,
    type            VARCHAR(20) NOT NULL
                     CHECK (type IN ('card','bank_account','wallet','crypto')),
    card_brand      VARCHAR(20),    -- visa, mastercard, amex, etc.
    last4           CHAR(4),        -- Only last 4 digits (PCI-DSS compliant)
    exp_month       SMALLINT CHECK (exp_month BETWEEN 1 AND 12),
    exp_year        SMALLINT,
    token           VARCHAR(255) NOT NULL,  -- Vault token (card number never stored)
    fingerprint     VARCHAR(64),            -- SHA-256 to identify duplicate cards
    is_default      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_pm_customer ON core.payment_methods(customer_id);
CREATE INDEX idx_pm_fingerprint ON core.payment_methods(fingerprint);

-- =============================================================================
-- TRANSACTIONS (table principale — high volume)
-- =============================================================================

CREATE TABLE core.transactions (
    transaction_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    merchant_id     UUID NOT NULL REFERENCES core.merchants(merchant_id),
    customer_id     UUID NOT NULL REFERENCES core.customers(customer_id),
    payment_method_id UUID NOT NULL REFERENCES core.payment_methods(payment_method_id),
    amount          NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    currency_code   CHAR(3) NOT NULL REFERENCES reference.currencies(currency_code),
    amount_usd      NUMERIC(18,2),  -- Pre-calculé via trigger ou application
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','authorized','captured','failed','refunded','disputed')),
    failure_reason  VARCHAR(100),
    ip_address      INET,
    user_agent      TEXT,
    device_type     VARCHAR(20) CHECK (device_type IN ('mobile','desktop','tablet','api','other')),
    fraud_score     NUMERIC(5,4) DEFAULT 0.0 CHECK (fraud_score BETWEEN 0 AND 1),
    is_3d_secure    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes critiques (patterns d'accès attendus)
CREATE INDEX idx_tx_merchant_created ON core.transactions(merchant_id, created_at DESC);
CREATE INDEX idx_tx_customer_created ON core.transactions(customer_id, created_at DESC);
CREATE INDEX idx_tx_status ON core.transactions(status) WHERE status IN ('pending','failed','disputed');
CREATE INDEX idx_tx_created_brin ON core.transactions USING BRIN(created_at);  -- BRIN for time-series
CREATE INDEX idx_tx_fraud ON core.transactions(fraud_score DESC) WHERE fraud_score > 0.5;

-- =============================================================================
-- REFUNDS & DISPUTES
-- =============================================================================

CREATE TABLE core.refunds (
    refund_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id  UUID NOT NULL REFERENCES core.transactions(transaction_id),
    amount          NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    reason          VARCHAR(100),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','succeeded','failed')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_refunds_transaction ON core.refunds(transaction_id);

CREATE TABLE core.disputes (
    dispute_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id  UUID NOT NULL REFERENCES core.transactions(transaction_id),
    amount          NUMERIC(18,2) NOT NULL,
    reason          VARCHAR(50) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'needs_response'
                     CHECK (status IN ('needs_response','under_review','won','lost')),
    evidence_url    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);
CREATE INDEX idx_disputes_status ON core.disputes(status);

-- =============================================================================
-- AUDIT LOG (immutable, append-only — PCI-DSS Req. 10)
-- =============================================================================

CREATE TABLE audit.audit_log (
    audit_id        BIGSERIAL PRIMARY KEY,
    event_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_type      VARCHAR(20) NOT NULL,  -- user, system, admin
    actor_id        VARCHAR(100),
    action          VARCHAR(50) NOT NULL,  -- SELECT, INSERT, UPDATE, DELETE, LOGIN, etc.
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(100),
    ip_address      INET,
    success         BOOLEAN NOT NULL,
    metadata        JSONB
);
CREATE INDEX idx_audit_time ON audit.audit_log(event_time DESC);
CREATE INDEX idx_audit_actor ON audit.audit_log(actor_id, event_time DESC);
CREATE INDEX idx_audit_resource ON audit.audit_log(resource_type, resource_id);

-- Revoke DELETE/UPDATE (append-only)
REVOKE UPDATE, DELETE ON audit.audit_log FROM PUBLIC;

-- =============================================================================
-- TRIGGERS — updated_at auto-refresh
-- =============================================================================

CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_customers_updated BEFORE UPDATE ON core.customers
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER trg_merchants_updated BEFORE UPDATE ON core.merchants
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER trg_transactions_updated BEFORE UPDATE ON core.transactions
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- =============================================================================
-- REPLICATION (logical — pour Airbyte CDC)
-- =============================================================================

CREATE PUBLICATION stripe_publication FOR ALL TABLES;
-- Slot de réplication créé par Airbyte via :
-- SELECT pg_create_logical_replication_slot('airbyte_slot','pgoutput');
