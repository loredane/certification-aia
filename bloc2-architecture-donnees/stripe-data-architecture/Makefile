# =============================================================================
# FIX v3-mediums #24 : Makefile central pour les operations courantes.
# Usage : make <cible>
# =============================================================================

.PHONY: help up down restart seed generate dbt-deps dbt-run dbt-test dbt-docs \
        test-ml logs reset ps lint format clean validate

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Docker lifecycle
# ---------------------------------------------------------------------------

up: ## Demarre toute la stack (detached)
	docker compose up -d

down: ## Arrete la stack (garde les volumes)
	docker compose down

restart: ## Redemarre toute la stack
	docker compose restart

reset: ## DESTRUCTIF : arrete la stack ET supprime les volumes
	docker compose down -v

ps: ## Statut des services
	docker compose ps

logs: ## Logs agreges (-f pour suivre)
	docker compose logs --tail=100 -f

# ---------------------------------------------------------------------------
# Data seeding / generation
# ---------------------------------------------------------------------------

seed: ## Recharge le seed postgres (suppose postgres UP)
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-stripe_app} \
	  -d $${POSTGRES_DB:-stripe_oltp} -f /docker-entrypoint-initdb.d/02_seed.sql

generate: ## Genere 10 min de transactions (2 tx/s) via le generator
	python scripts/transaction-generator.py --rate 2 --duration 600 \
	  --ml-url http://localhost:8001

# ---------------------------------------------------------------------------
# dbt
# ---------------------------------------------------------------------------

dbt-deps: ## dbt deps (install packages)
	cd dbt/stripe_analytics && dbt deps --profiles-dir ..

dbt-run: ## dbt run (staging + marts)
	cd dbt/stripe_analytics && dbt run --profiles-dir .. --target dev

dbt-test: ## dbt test (schema + data tests)
	cd dbt/stripe_analytics && dbt test --profiles-dir .. --target dev

dbt-docs: ## Genere et sert la doc dbt sur :8085
	cd dbt/stripe_analytics && dbt docs generate --profiles-dir .. --target dev && \
	  dbt docs serve --profiles-dir .. --port 8085

# ---------------------------------------------------------------------------
# Tests & qualite
# ---------------------------------------------------------------------------

test-ml: ## pytest du ml-service dans le container
	docker compose exec -T ml-service pytest -q /app

lint: ## ruff + sqlfluff (nécessite pip install ruff sqlfluff sqlfluff-templater-dbt)
	ruff check .
	sqlfluff lint dbt/stripe_analytics/models || true

format: ## black + isort + sqlfluff fix
	black .
	isort .
	sqlfluff fix dbt/stripe_analytics/models || true

validate: ## Valide compose + py_compile + yaml
	docker compose config --quiet
	python -m py_compile airflow/dags/*.py ml-service/app/main.py scripts/transaction-generator.py
	@echo "OK"

clean: ## Supprime artefacts dbt / pytest / pycache
	rm -rf dbt/stripe_analytics/target dbt/stripe_analytics/dbt_packages \
	       dbt/stripe_analytics/logs \
	       .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
