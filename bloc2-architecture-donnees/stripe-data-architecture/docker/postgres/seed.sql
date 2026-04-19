-- =============================================================================
-- Seed data — référentiels + démo
-- =============================================================================

-- Currencies
INSERT INTO reference.currencies VALUES
    ('USD', 'US Dollar', 2, NOW()),
    ('EUR', 'Euro', 2, NOW()),
    ('GBP', 'British Pound', 2, NOW()),
    ('JPY', 'Japanese Yen', 0, NOW()),
    ('CAD', 'Canadian Dollar', 2, NOW()),
    ('AUD', 'Australian Dollar', 2, NOW()),
    ('CHF', 'Swiss Franc', 2, NOW()),
    ('SGD', 'Singapore Dollar', 2, NOW());

-- Countries
INSERT INTO reference.countries VALUES
    ('US', 'United States', 'North America', FALSE, NOW()),
    ('FR', 'France', 'Europe', FALSE, NOW()),
    ('GB', 'United Kingdom', 'Europe', FALSE, NOW()),
    ('DE', 'Germany', 'Europe', FALSE, NOW()),
    ('CA', 'Canada', 'North America', FALSE, NOW()),
    ('JP', 'Japan', 'Asia', FALSE, NOW()),
    ('AU', 'Australia', 'Oceania', FALSE, NOW()),
    ('SG', 'Singapore', 'Asia', FALSE, NOW()),
    ('NG', 'Nigeria', 'Africa', TRUE, NOW()),
    ('RU', 'Russia', 'Europe', TRUE, NOW());

-- MCC Codes (sample)
INSERT INTO reference.mcc_codes VALUES
    ('5411', 'Grocery Stores, Supermarkets', 'Retail'),
    ('5812', 'Eating Places and Restaurants', 'Food'),
    ('5813', 'Drinking Places (Bars, Lounges)', 'Food'),
    ('5814', 'Fast Food Restaurants', 'Food'),
    ('5999', 'Miscellaneous Specialty Retail', 'Retail'),
    ('7372', 'Computer Software', 'Digital'),
    ('7995', 'Gambling', 'Entertainment'),
    ('4722', 'Travel Agencies', 'Travel'),
    ('4511', 'Airlines', 'Travel'),
    ('5967', 'Adult Content Services', 'Entertainment');

-- Exchange rates (sample)
INSERT INTO reference.exchange_rates (from_currency, to_currency, rate, effective_date) VALUES
    ('EUR', 'USD', 1.08, CURRENT_DATE),
    ('GBP', 'USD', 1.27, CURRENT_DATE),
    ('JPY', 'USD', 0.0067, CURRENT_DATE),
    ('CAD', 'USD', 0.74, CURRENT_DATE),
    ('AUD', 'USD', 0.66, CURRENT_DATE),
    ('CHF', 'USD', 1.12, CURRENT_DATE),
    ('SGD', 'USD', 0.75, CURRENT_DATE);

-- Sample customers
INSERT INTO core.customers (email, email_hash, first_name, last_name, country_code, kyc_status, risk_score) VALUES
    ('alice@example.com', encode(digest('alice@example.com','sha256'),'hex'), 'Alice', 'Dupont', 'FR', 'verified', 0.05),
    ('bob@example.com', encode(digest('bob@example.com','sha256'),'hex'), 'Bob', 'Smith', 'US', 'verified', 0.12),
    ('carol@example.com', encode(digest('carol@example.com','sha256'),'hex'), 'Carol', 'Jones', 'GB', 'verified', 0.08),
    ('dave@example.com', encode(digest('dave@example.com','sha256'),'hex'), 'Dave', 'Lee', 'SG', 'pending', 0.22);

-- Sample merchants
INSERT INTO core.merchants (business_name, business_type, mcc_code, country_code, status) VALUES
    ('Le Petit Bistro', 'company', '5812', 'FR', 'active'),
    ('TechSoft Inc', 'company', '7372', 'US', 'active'),
    ('UK Groceries Ltd', 'company', '5411', 'GB', 'active'),
    ('Sakura Airlines', 'company', '4511', 'JP', 'active'),
    ('Singapore Hotels', 'company', '4722', 'SG', 'active');

-- FIX v3-mediums #4 : une carte par client seedé.
-- Sans ça, dbt produit des marts vides si dbt tourne AVANT le transaction-generator.
-- Token / fingerprint fictifs (PCI-DSS Req 3.2 : CCN jamais stocké).
INSERT INTO core.payment_methods
    (customer_id, type, card_brand, last4, exp_month, exp_year, token, fingerprint, is_default)
SELECT
    c.customer_id,
    'card',
    (ARRAY['visa','mastercard','amex','visa','mastercard'])[1 + (ABS(hashtext(c.email_hash)) % 5)],
    LPAD((ABS(hashtext(c.email_hash)) % 10000)::TEXT, 4, '0'),
    1 + (ABS(hashtext(c.email_hash || 'm')) % 12),
    2027 + (ABS(hashtext(c.email_hash || 'y')) % 5),
    'tok_seed_' || encode(gen_random_bytes(8), 'hex'),
    encode(digest(c.email_hash || 'fp', 'sha256'), 'hex'),
    TRUE
FROM core.customers c
ON CONFLICT DO NOTHING;

-- Une deuxième carte (bank_account) pour Alice et Bob, pour couvrir le cas
-- multi-instruments dans les requêtes de démo.
INSERT INTO core.payment_methods
    (customer_id, type, card_brand, last4, exp_month, exp_year, token, fingerprint, is_default)
SELECT
    c.customer_id,
    'bank_account',
    NULL,
    NULL,
    NULL,
    NULL,
    'tok_ba_' || encode(gen_random_bytes(8), 'hex'),
    encode(digest(c.email_hash || 'ba', 'sha256'), 'hex'),
    FALSE
FROM core.customers c
WHERE c.email IN ('alice@example.com', 'bob@example.com')
ON CONFLICT DO NOTHING;
