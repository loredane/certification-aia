-- =============================================================================
-- Snowflake Setup — Stripe Data Warehouse
-- DAMA-DMBOK2 ch.6 §1.3.4 — Data Warehouse architecture
-- DAMA-DMBOK2 ch.7 §1.3 — Access control, least privilege
-- =============================================================================
-- Execute as ACCOUNTADMIN (or SECURITYADMIN for roles)
--
-- FIX v3-mediums #7 : passwords Airbyte/dbt désormais passés en variables
-- snowsql (pas de hardcode 'Change_Me_*' dans le source committé).
--
-- Usage (snowsql CLI) :
--   snowsql -a <account> -u <admin> -f 01_setup_snowflake.sql \
--           -D airbyte_password="$SNOWFLAKE_AIRBYTE_PASSWORD" \
--           -D dbt_password="$SNOWFLAKE_PASSWORD"
--
-- Usage (Snowsight worksheets) :
--   !set variable_substitution=true;
--   !define airbyte_password=...;
--   !define dbt_password=...;
--   !source 01_setup_snowflake.sql;
-- =============================================================================
!set variable_substitution=true;

USE ROLE ACCOUNTADMIN;

-- =============================================================================
-- 1. WAREHOUSES (compute) — separate by workload for cost control
-- =============================================================================

CREATE WAREHOUSE IF NOT EXISTS LOADING
    WAREHOUSE_SIZE = XSMALL
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Airbyte ingestion workload';

CREATE WAREHOUSE IF NOT EXISTS TRANSFORMING
    WAREHOUSE_SIZE = SMALL
    AUTO_SUSPEND = 300
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'dbt transformations';

CREATE WAREHOUSE IF NOT EXISTS REPORTING
    WAREHOUSE_SIZE = SMALL
    AUTO_SUSPEND = 600
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'BI dashboards, ad-hoc queries';

-- =============================================================================
-- 2. DATABASES — medallion architecture
-- =============================================================================

CREATE DATABASE IF NOT EXISTS RAW
    COMMENT = 'Raw data landed by Airbyte from sources';

CREATE DATABASE IF NOT EXISTS STRIPE_ANALYTICS
    COMMENT = 'Transformed data (staging + marts)';

-- Schemas
CREATE SCHEMA IF NOT EXISTS RAW.STRIPE
    COMMENT = 'Raw PostgreSQL OLTP replica';

CREATE SCHEMA IF NOT EXISTS RAW.REFERENCE
    COMMENT = 'Reference data (countries, currencies, MCC)';

CREATE SCHEMA IF NOT EXISTS STRIPE_ANALYTICS.STAGING
    COMMENT = 'Cleaned, typed staging models (dbt)';

CREATE SCHEMA IF NOT EXISTS STRIPE_ANALYTICS.MARTS
    COMMENT = 'Business-ready star schema (dbt)';

CREATE SCHEMA IF NOT EXISTS STRIPE_ANALYTICS.REPORTS
    COMMENT = 'Aggregated reports, materialized views';

-- =============================================================================
-- 3. ROLES — RBAC hierarchy (least privilege)
-- =============================================================================

USE ROLE SECURITYADMIN;

CREATE ROLE IF NOT EXISTS LOADER_ROLE
    COMMENT = 'Airbyte — write to RAW only';

CREATE ROLE IF NOT EXISTS TRANSFORM_ROLE
    COMMENT = 'dbt — read RAW, write STRIPE_ANALYTICS';

CREATE ROLE IF NOT EXISTS ANALYST_ROLE
    COMMENT = 'Data analysts — read STRIPE_ANALYTICS only';

CREATE ROLE IF NOT EXISTS DATA_ENG_ROLE
    COMMENT = 'Data engineers — full access for debug';

-- =============================================================================
-- 4. GRANTS
-- =============================================================================

-- LOADER (Airbyte)
GRANT USAGE ON WAREHOUSE LOADING TO ROLE LOADER_ROLE;
GRANT USAGE ON DATABASE RAW TO ROLE LOADER_ROLE;
GRANT USAGE ON SCHEMA RAW.STRIPE TO ROLE LOADER_ROLE;
GRANT USAGE ON SCHEMA RAW.REFERENCE TO ROLE LOADER_ROLE;
GRANT CREATE TABLE, CREATE VIEW ON SCHEMA RAW.STRIPE TO ROLE LOADER_ROLE;
GRANT CREATE TABLE, CREATE VIEW ON SCHEMA RAW.REFERENCE TO ROLE LOADER_ROLE;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA RAW.STRIPE TO ROLE LOADER_ROLE;
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN SCHEMA RAW.STRIPE TO ROLE LOADER_ROLE;

-- TRANSFORMER (dbt)
GRANT USAGE ON WAREHOUSE TRANSFORMING TO ROLE TRANSFORM_ROLE;
GRANT USAGE ON DATABASE RAW TO ROLE TRANSFORM_ROLE;
GRANT USAGE ON ALL SCHEMAS IN DATABASE RAW TO ROLE TRANSFORM_ROLE;
GRANT SELECT ON ALL TABLES IN DATABASE RAW TO ROLE TRANSFORM_ROLE;
GRANT SELECT ON FUTURE TABLES IN DATABASE RAW TO ROLE TRANSFORM_ROLE;

GRANT USAGE ON DATABASE STRIPE_ANALYTICS TO ROLE TRANSFORM_ROLE;
GRANT USAGE, CREATE SCHEMA ON DATABASE STRIPE_ANALYTICS TO ROLE TRANSFORM_ROLE;
GRANT ALL ON SCHEMA STRIPE_ANALYTICS.STAGING TO ROLE TRANSFORM_ROLE;
GRANT ALL ON SCHEMA STRIPE_ANALYTICS.MARTS TO ROLE TRANSFORM_ROLE;
GRANT ALL ON SCHEMA STRIPE_ANALYTICS.REPORTS TO ROLE TRANSFORM_ROLE;

-- ANALYST (BI read-only)
GRANT USAGE ON WAREHOUSE REPORTING TO ROLE ANALYST_ROLE;
GRANT USAGE ON DATABASE STRIPE_ANALYTICS TO ROLE ANALYST_ROLE;
GRANT USAGE ON ALL SCHEMAS IN DATABASE STRIPE_ANALYTICS TO ROLE ANALYST_ROLE;
GRANT SELECT ON ALL TABLES IN DATABASE STRIPE_ANALYTICS TO ROLE ANALYST_ROLE;
GRANT SELECT ON FUTURE TABLES IN DATABASE STRIPE_ANALYTICS TO ROLE ANALYST_ROLE;

-- DATA ENGINEER (full debug access)
GRANT ROLE LOADER_ROLE TO ROLE DATA_ENG_ROLE;
GRANT ROLE TRANSFORM_ROLE TO ROLE DATA_ENG_ROLE;
GRANT ROLE ANALYST_ROLE TO ROLE DATA_ENG_ROLE;

-- =============================================================================
-- 5. TECHNICAL USERS (service accounts)
-- =============================================================================

USE ROLE USERADMIN;

CREATE USER IF NOT EXISTS AIRBYTE_USER
    PASSWORD = '&airbyte_password'
    DEFAULT_ROLE = LOADER_ROLE
    DEFAULT_WAREHOUSE = LOADING
    MUST_CHANGE_PASSWORD = FALSE
    COMMENT = 'Technical user — Airbyte ELT';

CREATE USER IF NOT EXISTS DBT_USER
    PASSWORD = '&dbt_password'
    DEFAULT_ROLE = TRANSFORM_ROLE
    DEFAULT_WAREHOUSE = TRANSFORMING
    MUST_CHANGE_PASSWORD = FALSE
    COMMENT = 'Technical user — dbt transformations';

USE ROLE SECURITYADMIN;
GRANT ROLE LOADER_ROLE TO USER AIRBYTE_USER;
GRANT ROLE TRANSFORM_ROLE TO USER DBT_USER;

-- =============================================================================
-- 6. VERIFICATION
-- =============================================================================

SHOW WAREHOUSES;
SHOW DATABASES;
SHOW ROLES;
SHOW USERS;
