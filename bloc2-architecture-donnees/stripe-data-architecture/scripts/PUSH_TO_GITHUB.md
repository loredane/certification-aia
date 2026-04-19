# Guide de push sur GitHub

## 1. Créer le repo sur GitHub

1. Aller sur https://github.com/new
2. Nom : `stripe-data-architecture`
3. Description : *AIA RNCP38777 - Bloc 2 - Stripe Data Architecture (OLTP + OLAP + NoSQL)*
4. **Public** (le jury doit pouvoir accéder) ou **Private** + inviter le jury
5. **Ne pas** cocher "Initialize with README" (on en a déjà un)
6. Créer

## 2. Préparer le repo local

Depuis le dossier décompressé :

```bash
cd stripe-data-architecture

# Vérifier que .env n'est PAS présent (juste .env.example)
ls -la .env*
# Doit afficher UNIQUEMENT .env.example

# Init git
git init
git branch -M main
```

## 3. Premier commit

```bash
git add .
git status  # Vérifier qu'aucun secret n'est staged

git commit -m "Initial commit - Bloc 2 Stripe data architecture

- Stack: PostgreSQL OLTP + Snowflake DWH + MongoDB NoSQL
- Pipeline: Airbyte ELT + Kafka streaming + Airflow orchestration
- ML: FastAPI fraud scoring service
- Monitoring: Prometheus + Grafana
- IaC: Docker Compose + Terraform AWS mirror
- Docs: architecture, deployment, specifications"
```

## 4. Push

Remplace `<ton-user>` :

```bash
git remote add origin https://github.com/<ton-user>/stripe-data-architecture.git
git push -u origin main
```

Si GitHub te demande un token au lieu du mot de passe :
- GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
- Generate new token, scope `repo` suffit, expiration 30 jours
- Utiliser ce token comme mot de passe

## 5. Vérifier sur GitHub

- README s'affiche correctement en landing
- `.env` **absent** du repo (ne doit pas apparaître dans les fichiers)
- `.env.example` présent
- Arborescence complète visible

## 6. Donner accès au jury

**Si public** : rien à faire, l'URL suffit.

**Si private** :
- GitHub repo → Settings → Collaborators → Add people
- Ajouter les emails du jury avec rôle "Read"

## 7. URL à communiquer au jury

```
https://github.com/<ton-user>/stripe-data-architecture
```

À inclure :
- Dans la présentation PowerPoint (slide "Démo / Déploiement")
- Dans le document Word de synthèse (section livrable 10)
- Dans la description de la vidéo capture pipeline (livrable 11)

## 8. Dernière vérification avant soutenance

```bash
# Cloner depuis zéro dans un autre dossier pour simuler ce que le jury verra
cd /tmp
git clone https://github.com/<ton-user>/stripe-data-architecture.git test-clone
cd test-clone

# Vérifier que tout est là
ls -la
cat README.md | head -20
docker compose config  # Doit se parser sans erreur
```

Si tout est OK → tu es prête.
