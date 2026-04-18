-- =============================================================================
-- Stripe OLTP Schema — PostgreSQL 16
-- Modèle 3NF normalisé (DAMA-DMBOK2 ch.5 §1.3.5)
-- ACID, WAL logique pour CDC, partitioning, RBAC, audit append-only
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- SCHEMAS (séparation logique)
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS core;      -- Entités métier
CREATE SCHEMA IF NOT EXISTS reference; -- Données référentielles
CREATE SCHEMA IF NOT EXISTS audit;     -- Traçabilité (DAMA ch.7 §1.3.2)

-- =============================================================================
-- REFERENCE DATA (slow-changing)
-- =============================================================================
CREATE TABLE reference.country (
    country_code CHAR(2) PRIMARY KEY,
    country_name VARCHAR(100) NOT NULL,
    region       VARCHAR(50),
    is_eu        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE reference.currency (
    currency_code CHAR(3) PRIMARY KEY,
    currency_name VARCHAR(50) NOT NULL,
    decimals      SMALLINT NOT NULL DEFAULT 2
);

CREATE TABLE reference.exchange_rate (
    exchange_rate_id UUID DEFAULT uuid_generate_v4(),
    from_currency    CHAR(3) NOT NULL REFERENCES reference.currency(currency_code),
    to_currency      CHAR(3) NOT NULL REFERENCES reference.currency(currency_code),
    rate             NUMERIC(15,6) NOT NULL CHECK (rate > 0),
    effective_date   DATE NOT NULL,
    PRIMARY KEY (exchange_rate_id),
    UNIQUE (from_currency, to_currency, effective_date)
);

CREATE TABLE reference.payment_method_type (
    payment_method_type_id SERIAL PRIMARY KEY,
    type_code VARCHAR(30) UNIQUE NOT NULL,  -- card, sepa, ach, wallet...
    type_name VARCHAR(100) NOT NULL
);

-- =============================================================================
-- CORE — CUSTOMERS
-- =============================================================================
CREATE TABLE core.customer (
    customer_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    first_name      VARCHAR(100),
    last_name       VARCHAR(100),
    country_code    CHAR(2) NOT NULL REFERENCES reference.country(country_code),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- GDPR (DAMA ch.7 §1.3.1) : soft delete via flag + timestamp d'anonymisation
    is_deleted      BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT chk_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);
CREATE INDEX idx_customer_country ON core.customer(country_code);
CREATE INDEX idx_customer_created ON core.customer(created_at DESC);

-- =============================================================================
-- CORE — MERCHANTS
-- =============================================================================
CREATE TABLE core.merchant (
    merchant_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_name VARCHAR(200) NOT NULL,
    mcc_code      CHAR(4),  -- Merchant Category Code (PCI-DSS)
    country_code  CHAR(2) NOT NULL REFERENCES reference.country(country_code),
    kyc_status    VARCHAR(20) NOT NULL DEFAULT 'pending'
                  CHECK (kyc_status IN ('pending', 'verified', 'rejected')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_merchant_country ON core.merchant(country_code);
CREATE INDEX idx_merchant_kyc ON core.merchant(kyc_status);

-- =============================================================================
-- CORE — PAYMENT METHODS (tokenisation PCI-DSS)
-- =============================================================================
CREATE TABLE core.payment_method (
    payment_method_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id            UUID NOT NULL REFERENCES core.customer(customer_id),
    payment_method_type_id INT NOT NULL REFERENCES reference.payment_method_type(payment_method_type_id),
    -- Jamais de PAN en clair (PCI-DSS req. 3.4) — uniquement token + last4
    token                  VARCHAR(255) NOT NULL UNIQUE,
    last4                  CHAR(4),
    brand                  VARCHAR(30),     -- visa, mastercard, amex...
    exp_month              SMALLINT CHECK (exp_month BETWEEN 1 AND 12),
    exp_year               SMALLINT CHECK (exp_year BETWEEN 2020 AND 2050),
    is_default             BOOLEAN NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pm_customer ON core.payment_method(customer_id);

-- =============================================================================
-- CORE — TRANSACTIONS (partitionnée par mois — DAMA ch.6 §2.3)
-- =============================================================================
CREATE TABLE core.transaction (
    transaction_id    UUID DEFAULT uuid_generate_v4(),
    merchant_id       UUID NOT NULL REFERENCES core.merchant(merchant_id),
    customer_id       UUID NOT NULL REFERENCES core.customer(customer_id),
    payment_method_id UUID NOT NULL REFERENCES core.payment_method(payment_method_id),
    amount_minor      BIGINT NOT NULL CHECK (amount_minor > 0),  -- cents
    currency_code     CHAR(3) NOT NULL REFERENCES reference.currency(currency_code),
    status            VARCHAR(20) NOT NULL
                      CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded', 'disputed')),
    fraud_score       NUMERIC(4,3) CHECK (fraud_score BETWEEN 0 AND 1),
    fraud_decision    VARCHAR(20) CHECK (fraud_decision IN ('approve', 'review', 'decline')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (transaction_id, created_at)
) PARTITION BY RANGE (created_at);

-- Partitions mensuelles
CREATE TABLE core.transaction_2026_01 PARTITION OF core.transaction
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE core.transaction_2026_02 PARTITION OF core.transaction
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE core.transaction_2026_03 PARTITION OF core.transaction
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE core.transaction_2026_04 PARTITION OF core.transaction
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE core.transaction_2026_05 PARTITION OF core.transaction
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE core.transaction_default PARTITION OF core.transaction DEFAULT;

CREATE INDEX idx_tx_merchant ON core.transaction(merchant_id, created_at DESC);
CREATE INDEX idx_tx_customer ON core.transaction(customer_id, created_at DESC);
CREATE INDEX idx_tx_status   ON core.transaction(status) WHERE status IN ('pending', 'disputed');
CREATE INDEX idx_tx_fraud    ON core.transaction(fraud_score DESC) WHERE fraud_score > 0.7;

-- =============================================================================
-- CORE — REFUNDS & DISPUTES (entités liées aux transactions)
-- =============================================================================
CREATE TABLE core.refund (
    refund_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID NOT NULL,
    amount_minor   BIGINT NOT NULL CHECK (amount_minor > 0),
    reason         VARCHAR(100),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_refund_tx ON core.refund(transaction_id);

CREATE TABLE core.dispute (
    dispute_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID NOT NULL,
    reason_code    VARCHAR(50),
    status         VARCHAR(20) NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'won', 'lost', 'withdrawn')),
    evidence_due   DATE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dispute_tx ON core.dispute(transaction_id);
CREATE INDEX idx_dispute_status ON core.dispute(status);

-- =============================================================================
-- AUDIT — Append-only (DAMA ch.7 §1.3.2 + PCI-DSS req. 10)
-- =============================================================================
CREATE TABLE audit.access_log (
    audit_id    BIGSERIAL PRIMARY KEY,
    event_time  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    db_user     VARCHAR(100) NOT NULL,
    action      VARCHAR(20) NOT NULL,     -- INSERT/UPDATE/DELETE/SELECT
    table_name  VARCHAR(100) NOT NULL,
    row_pk      TEXT,
    old_values  JSONB,
    new_values  JSONB,
    client_ip   INET
);
CREATE INDEX idx_audit_time  ON audit.access_log(event_time DESC);
CREATE INDEX idx_audit_user  ON audit.access_log(db_user, event_time DESC);
CREATE INDEX idx_audit_table ON audit.access_log(table_name);

-- Trigger générique d'audit
CREATE OR REPLACE FUNCTION audit.log_changes() RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit.access_log(db_user, action, table_name, row_pk, old_values, new_values)
    VALUES (
        current_user,
        TG_OP,
        TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        COALESCE((NEW)::text, (OLD)::text),
        CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN row_to_json(OLD)::jsonb ELSE NULL END,
        CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN row_to_json(NEW)::jsonb ELSE NULL END
    );
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER trg_audit_transaction
    AFTER INSERT OR UPDATE OR DELETE ON core.transaction
    FOR EACH ROW EXECUTE FUNCTION audit.log_changes();

CREATE TRIGGER trg_audit_customer
    AFTER INSERT OR UPDATE OR DELETE ON core.customer
    FOR EACH ROW EXECUTE FUNCTION audit.log_changes();

-- =============================================================================
-- RBAC — Rôles applicatifs (DAMA ch.7 §1.3.4)
-- =============================================================================
CREATE ROLE app_read;
CREATE ROLE app_write;
CREATE ROLE analytics_ro;

GRANT USAGE ON SCHEMA core, reference TO app_read, app_write, analytics_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA core, reference TO app_read, analytics_ro;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core TO app_write;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA core TO app_write;

-- Interdiction de lire la table audit pour app_write
REVOKE ALL ON SCHEMA audit FROM app_read, app_write;
GRANT USAGE ON SCHEMA audit TO analytics_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA audit TO analytics_ro;

-- Utilisateur CDC pour Debezium (replication)
CREATE USER debezium WITH REPLICATION ENCRYPTED PASSWORD 'debezium_pwd';
GRANT USAGE ON SCHEMA core TO debezium;
GRANT SELECT ON ALL TABLES IN SCHEMA core TO debezium;

-- Publication pour logical replication (CDC)
CREATE PUBLICATION stripe_publication FOR TABLE
    core.transaction, core.customer, core.merchant, core.payment_method;

-- =============================================================================
-- VIEWS métier
-- =============================================================================
CREATE OR REPLACE VIEW core.v_active_customer AS
SELECT customer_id, email, first_name, last_name, country_code, created_at
FROM core.customer
WHERE is_deleted = FALSE;

COMMENT ON SCHEMA core IS 'Entités métier transactionnelles (OLTP)';
COMMENT ON SCHEMA reference IS 'Données référentielles slowly-changing';
COMMENT ON SCHEMA audit IS 'Traçabilité append-only PCI-DSS req. 10';
