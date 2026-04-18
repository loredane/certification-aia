-- =============================================================================
-- Seed data - Référentiel + quelques entités pour démarrage démo
-- =============================================================================

-- Countries
INSERT INTO reference.country (country_code, country_name, region, is_eu) VALUES
  ('FR', 'France', 'EU', TRUE),
  ('DE', 'Germany', 'EU', TRUE),
  ('ES', 'Spain', 'EU', TRUE),
  ('IT', 'Italy', 'EU', TRUE),
  ('NL', 'Netherlands', 'EU', TRUE),
  ('GB', 'United Kingdom', 'EU', FALSE),
  ('US', 'United States', 'AMER', FALSE),
  ('CA', 'Canada', 'AMER', FALSE),
  ('JP', 'Japan', 'APAC', FALSE),
  ('AU', 'Australia', 'APAC', FALSE),
  ('IN', 'India', 'APAC', FALSE),
  ('BR', 'Brazil', 'AMER', FALSE),
  ('SG', 'Singapore', 'APAC', FALSE);

-- Currencies
INSERT INTO reference.currency (currency_code, currency_name, decimals) VALUES
  ('EUR', 'Euro', 2),
  ('USD', 'US Dollar', 2),
  ('GBP', 'British Pound', 2),
  ('JPY', 'Japanese Yen', 0),
  ('CAD', 'Canadian Dollar', 2),
  ('AUD', 'Australian Dollar', 2),
  ('INR', 'Indian Rupee', 2),
  ('BRL', 'Brazilian Real', 2),
  ('SGD', 'Singapore Dollar', 2);

-- Exchange rates (indicatifs)
INSERT INTO reference.exchange_rate (from_currency, to_currency, rate, effective_date) VALUES
  ('EUR', 'USD', 1.082000, '2026-04-19'),
  ('USD', 'EUR', 0.924000, '2026-04-19'),
  ('GBP', 'USD', 1.265000, '2026-04-19'),
  ('USD', 'GBP', 0.790500, '2026-04-19'),
  ('EUR', 'GBP', 0.855500, '2026-04-19'),
  ('USD', 'JPY', 154.200000, '2026-04-19'),
  ('EUR', 'JPY', 166.850000, '2026-04-19');

-- Payment method types
INSERT INTO reference.payment_method_type (type_code, type_name) VALUES
  ('card',   'Credit / Debit Card'),
  ('sepa',   'SEPA Direct Debit'),
  ('ach',    'ACH Bank Transfer'),
  ('wallet', 'Digital Wallet (Apple Pay / Google Pay)'),
  ('bnpl',   'Buy Now Pay Later'),
  ('crypto', 'Cryptocurrency');

-- Exemples de customers
INSERT INTO core.customer (email, first_name, last_name, country_code) VALUES
  ('marie.dupont@example.fr', 'Marie', 'Dupont', 'FR'),
  ('john.smith@example.com', 'John', 'Smith', 'US'),
  ('anna.mueller@example.de', 'Anna', 'Mueller', 'DE'),
  ('sato.yuki@example.jp', 'Yuki', 'Sato', 'JP'),
  ('carlos.silva@example.br', 'Carlos', 'Silva', 'BR');

-- Exemples de merchants
INSERT INTO core.merchant (business_name, mcc_code, country_code, kyc_status) VALUES
  ('Parisian Bakery SAS', '5812', 'FR', 'verified'),
  ('Global E-Shop Inc',   '5999', 'US', 'verified'),
  ('Berlin Tech GmbH',    '7372', 'DE', 'verified'),
  ('Tokyo Subscription',  '5968', 'JP', 'verified'),
  ('São Paulo Travel',    '4722', 'BR', 'pending');
