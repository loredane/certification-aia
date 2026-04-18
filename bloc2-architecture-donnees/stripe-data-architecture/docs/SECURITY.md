# Sécurité et conformité · Stripe Data Platform

Contrôles de sécurité et mesures de conformité **GDPR / PCI-DSS / CCPA** implémentés dans la plateforme. Références DAMA-DMBOK2 ch.7 (Data Security) citées à chaque contrôle.

## 1. Chiffrement

### 1.1 At rest

PostgreSQL utilise `pgcrypto` pour les colonnes sensibles applicatives (DAMA ch.7 §1.3.1.2). En production cloud, le TDE du moteur (AWS RDS, GCP Cloud SQL, Azure Database) chiffre en AES-256 de manière transparente les data files et les WAL.

ClickHouse et MongoDB utilisent le chiffrement disque natif (`encrypted_fs` ou LUKS) sur les volumes.

### 1.2 In transit

TLS 1.2 minimum partout. En prod, les connection strings forcent `sslmode=require` (PostgreSQL), `tls=true` (MongoDB), `secure=true` (ClickHouse). Kafka utilise `SASL_SSL` avec SCRAM sur les listeners prod.

## 2. Tokenisation PCI-DSS

La table `core.payment_method` ne stocke **jamais** de PAN (Primary Account Number) en clair (PCI-DSS req. 3.4). Ce qui est stocké :

- Un **token** opaque émis par un tokenization service externe
- Les **4 derniers chiffres** (`last4`) pour l'affichage UI
- La **brand** : visa, mastercard, amex, discover
- Le **mois/année d'expiration** — non sensible

Le CVV n'est stocké nulle part, conformément à PCI-DSS req. 3.2.

## 3. Audit append-only (PCI-DSS req. 10)

Le schéma `audit.access_log` est **append-only** : aucun UPDATE ni DELETE autorisé applicativement. Seul le super-user peut faire de la maintenance (purges selon calendrier de rétention).

Un trigger générique (`audit.log_changes()`) capture automatiquement tous les INSERT / UPDATE / DELETE sur les tables sensibles (`core.transaction`, `core.customer`) :

- L'utilisateur DB
- L'action
- Les valeurs `old` et `new` sérialisées en JSONB
- Timestamp et IP client si dispo

Trois index pour accélérer les recherches forensics : par timestamp, par user, par table.

## 4. RBAC

### 4.1 PostgreSQL

Quatre rôles applicatifs (DAMA ch.7 §1.3.4) :

- `app_read` → SELECT sur `core` et `reference`, rien sur `audit`
- `app_write` → INSERT / UPDATE / SELECT sur `core`, rien sur `audit`
- `analytics_ro` → SELECT partout y compris `audit` (reporting conformité)
- `debezium` → CDC uniquement, privilège `REPLICATION`

**Moindre privilège** appliqué strictement : même les applis ne peuvent pas DELETE dans `core.transaction`. Les remboursements passent par `core.refund`, une table dédiée.

### 4.2 ClickHouse

Deux rôles : `read_only` (SELECT sur tout `stripe_olap`) et `read_only_anon` (SELECT uniquement sur les tables agrégées, pas sur `dim_customer` qui contient l'email hashé).

### 4.3 MongoDB

Trois rôles métier :

- `feature_store_reader` → lecture feature store pour les services ML
- `fraud_analyst` → lecture/écriture `fraud_alerts`, lecture logs
- `logs_reader` → lecture logs et clickstream

## 5. Conformité GDPR

### 5.1 Droit à l'oubli (Art. 17)

`core.customer` a un flag `is_deleted` et un timestamp `deleted_at`. Quand un client demande l'effacement, un job Airflow :

1. Passe `is_deleted = TRUE` et `deleted_at = NOW()` — soft delete immédiat
2. Pseudonymise les champs directement identifiants : `email = 'redacted@…'`, `first_name = 'REDACTED'`, `last_name = 'REDACTED'`
3. Propage l'effacement downstream : anonymisation de `dim_customer` dans ClickHouse (on garde le hash de l'email pour la continuité analytique), suppression des features dans `ml_feature_store` MongoDB, purge du `user_id` clickstream correspondant

Le hard delete physique intervient après la rétention légale PCI-DSS (1 an minimum) ou fiscale (7 ans en général).

### 5.2 Portabilité (Art. 20)

Endpoint applicatif qui exporte en JSON toutes les données perso d'un customer : profil, transactions, payment methods (sans le token — c'est une donnée technique), feedback, sessions clickstream.

### 5.3 Consentement (Art. 7)

Le consentement marketing / analytics se trace dans une table dédiée. Pas implémenté dans le repo, mais le design le prévoit via `core.customer.consent_flags JSONB`.

## 6. Conformité PCI-DSS

Les 12 requirements adressés comme suit :

| Req. | Contrôle | Implémentation |
|---|---|---|
| 1 | Firewall | Docker network isolé, pas de port exposé hors localhost en dev |
| 2 | Default passwords | `.env.example` avec secrets à changer, jamais de default en prod |
| 3 | Tokenisation | `core.payment_method` sans PAN ni CVV |
| 4 | Chiffrement transit | TLS 1.2+ sur toutes les connexions prod |
| 5 | Antivirus | Hors scope infra applicative |
| 6 | Secure dev | Git, revue obligatoire, tests dbt automatisés |
| 7 | Moindre privilège | RBAC §4 |
| 8 | Identification unique | Un user par service |
| 9 | Accès physique | Cloud provider (N/A en local) |
| 10 | Audit trail | `audit.access_log` append-only, trigger générique |
| 11 | Security testing | Scans de vulnérabilité dans pipeline CI séparé |
| 12 | Politique sécurité | Ce document |

## 7. Conformité CCPA

Le CCPA s'aligne largement sur le GDPR. Spécifiquement, les résidents californiens peuvent :

- **Copie** des données collectées → mêmes mécanismes que GDPR Art.15
- **Suppression** → mêmes mécanismes que GDPR Art.17
- **Opt-out vente des données** → Stripe ne vend pas de données perso, donc structurellement non applicable

Le flag `customer.country_code = 'US'` combiné à une colonne `state_code` (extension possible) permet de déclencher le traitement CCPA pour les résidents californiens.

## 8. Rétention

| Donnée | Durée | Motif |
|---|---|---|
| Transactions OLTP | 7 ans | Fiscal + PCI-DSS |
| Fact transactions OLAP | 7 ans (TTL) | Aligné OLTP |
| Audit log | 7 ans minimum | PCI-DSS req. 10.7 |
| Event logs | 90 jours (TTL) | Valeur décroissante, coût de stockage |
| Clickstream | 180 jours (TTL) | Horizon ML raisonnable |
| Feature store | Pas de TTL | Overwrite horaire, toujours frais |
| Customer feedback | Pas de TTL applicatif | Effacement sur demande GDPR uniquement |

## 9. Observabilité sécurité

Extensions possibles sur les dashboards Grafana :

- Tentatives de login échouées par heure
- Pics inhabituels d'accès à `audit.access_log`
- Connexions depuis IP hors whitelist
- Volumétrie de lecture par user DB (détection exfiltration)

Pas implémenté dans ce repo. La config Prometheus + Grafana le permet via des scrapers custom.

## 10. Gestion des incidents

Hors scope du repo. Le plan IR type inclurait :

- **Détection** — alertes Grafana + SIEM externe
- **Contention** — révocation immédiate des credentials compromis
- **Éradication** — patch, rotation de clés
- **Récupération** — restore depuis backup WAL PostgreSQL
- **Post-mortem** documenté
- **Notification autorités** — CNIL sous 72h pour GDPR, PCI Council, clients concernés
