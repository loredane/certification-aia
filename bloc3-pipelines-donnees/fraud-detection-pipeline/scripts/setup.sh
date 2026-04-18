#!/bin/bash
# Script d'installation du pipeline Fraud Detection
# Usage: bash scripts/setup.sh

set -e

echo "🛡️  Installation du pipeline Fraud Detection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Créer les répertoires nécessaires
mkdir -p data models logs

# Copier le fichier d'environnement
if [ ! -f config/.env ]; then
    cp config/.env.example config/.env
    echo "✅ Fichier .env créé (à configurer)"
fi

# Vérifier Docker
if command -v docker &> /dev/null; then
    echo "✅ Docker détecté"

    echo "📦 Lancement de l'infrastructure..."
    docker-compose up -d

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "✅ Infrastructure lancée !"
    echo ""
    echo "   Airflow  : http://localhost:8080 (admin/admin)"
    echo "   MLflow   : http://localhost:5000"
    echo "   PostgreSQL : localhost:5432"
    echo ""
    echo "Prochaines étapes :"
    echo "  1. Activer les DAGs dans Airflow"
    echo "  2. Lancer train_model en premier"
    echo "  3. Puis activer stream_ingest"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "⚠️  Docker non détecté. Installation locale..."
    pip install -r requirements.txt
    python src/database/init_db.py
    python src/ml/train.py
    echo "✅ Installation locale terminée."
fi
