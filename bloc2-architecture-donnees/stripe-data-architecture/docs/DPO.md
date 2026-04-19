# Contacts Data Protection Officer (DPO) & CISO

> **FIX v3-mediums #21** — Promis par `docs/SPECIFICATIONS.md` §4.1 (GDPR — Data Protection Officer).
>
> **Note importante** : ce document est **fictif**. Stripe, le projet Bloc 2 AIA
> et les personnes nommees ci-dessous sont une simulation pour la certification
> RNCP38777. Toute ressemblance avec des personnes ou entites reelles serait
> fortuite.

---

## 1. Data Protection Officer (GDPR Art. 37-39)

| Champ | Valeur |
|---|---|
| Nom | *Mme Camille Bernard* (fictif) |
| Role | Data Protection Officer — Stripe EMEA |
| Entite | Stripe Payments Europe, Ltd. (fictif dans ce projet) |
| Adresse postale | 1 Grand Canal Street Lower, Dublin, Irlande |
| Email DPO | `dpo@stripe-demo.local` |
| Email exercice de droits | `privacy-rights@stripe-demo.local` |
| Telephone | +353 1 555 0100 |
| Autorite de controle de reference | Data Protection Commission (DPC), Irlande |

### Perimetre d'action

- Traitements OLTP (`core.customers`, `core.transactions`, `core.payment_methods`)
- Pipelines OLAP (Snowflake marts, dbt) et Data Lake (MinIO/S3)
- Collections NoSQL contenant des donnees personnelles
  (`clickstream_events`, `customer_feedback`, `ml_features_customer`)
- Revue des Analyses d'Impact Relatives a la Protection des Donnees (AIPD / DPIA)

### Procedure d'exercice de droits

Toute personne peut exercer ses droits (acces, rectification, effacement,
portabilite, opposition, limitation) en contactant `privacy-rights@stripe-demo.local`.
- Delai de reponse : 30 jours (prolongeable de 60 jours max, Art. 12.3).
- Chaine technique : ticket ServiceNow -> DAG Airflow `gdpr_subject_access_request`
  -> export JSON signe -> notification email au demandeur.

---

## 2. Chief Information Security Officer (PCI-DSS v4.0 Req 12.1)

| Champ | Valeur |
|---|---|
| Nom | *M. Julien Rousseau* (fictif) |
| Role | CISO — Stripe Platform |
| Email | `ciso@stripe-demo.local` |
| Telephone (astreinte 24/7) | +1 415 555 0199 |

### Perimetre

- Politique de securite globale (ISO 27001:2022)
- Conformite PCI-DSS v4.0 (perimetre Cardholder Data Environment - CDE)
- Gestion des incidents de securite majeurs (> Severity 2)
- Revue annuelle de la segmentation reseau (Req 1.2.1)
- Rotation des cles KMS, revue des acces privilegies (Req 7, 8)

---

## 3. Registre des traitements (Art. 30 GDPR) — extrait

| Traitement | Finalite | Base legale | Duree conservation | Categories de donnees |
|---|---|---|---|---|
| Autorisation paiement | Execution du contrat | Art. 6.1.b | 13 mois (preuve) + 10 ans (fiscal) | Identifiant client, montant, IP, device |
| Prevention fraude | Interet legitime | Art. 6.1.f + AIPD | 5 ans | Features ML, score de risque, decision |
| Analytics agreges | Interet legitime | Art. 6.1.f | 10 ans (agreges anonymises) | Revenus agreges, cohortes |
| Clickstream | Consentement | Art. 6.1.a | 90 jours (TTL MongoDB) | session_id, events, device, geo |
| Audit logs | Obligation legale | Art. 6.1.c (PCI-DSS Req 10) | 7 ans (archive S3 Glacier) | Actor, action, resource, IP |

---

## 4. Escalade et incidents

### Violation de donnees personnelles (data breach — GDPR Art. 33-34)

1. Detection (monitoring Grafana, SIEM, alerte CISO)
2. Notification interne CISO + DPO sous 1 heure
3. Qualification du risque (AIPD flash)
4. Notification autorite de controle (DPC Irlande) sous 72 heures si risque
5. Notification aux personnes concernees si risque eleve
6. Post-mortem + mesures correctives dans le runbook

### Incident securite operationnel

Voir `docs/runbook.md` (procedures on-call).
