.PHONY: help up down clean logs ps init-cdc generate demo dbt-run dbt-test

help:
	@echo "Commandes disponibles :"
	@echo "  make up         - Lance toute la stack"
	@echo "  make down       - Arrête la stack"
	@echo "  make clean      - Arrête + supprime les volumes"
	@echo "  make logs       - Affiche les logs de tous les services"
	@echo "  make ps         - Liste les services actifs"
	@echo "  make init-cdc   - Active le connecteur Debezium"
	@echo "  make generate   - Lance le générateur de transactions"
	@echo "  make demo       - Script demo complet (pour vidéo)"
	@echo "  make dbt-run    - Lance les modèles dbt"
	@echo "  make dbt-test   - Lance les tests dbt"

up:
	docker-compose up -d
	@echo "Stack en cours de démarrage... (30-60s)"
	@echo "Airflow  : http://localhost:8080"
	@echo "Grafana  : http://localhost:3000"
	@echo "Kafka UI : http://localhost:8081"

down:
	docker-compose down

clean:
	docker-compose down -v
	@echo "Volumes supprimés."

logs:
	docker-compose logs -f --tail=100

ps:
	docker-compose ps

init-cdc:
	bash scripts/init-debezium.sh

generate:
	docker-compose run --rm generator python generate.py --count 500

demo:
	bash scripts/demo.sh

dbt-run:
	docker-compose run --rm dbt dbt run --profiles-dir /root/.dbt

dbt-test:
	docker-compose run --rm dbt dbt test --profiles-dir /root/.dbt
