.PHONY: up down build seed ingest test lint openapi logs

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

seed:
	docker compose exec backend python -m app.db.seed

ingest:
	docker compose exec backend python -m app.ingestion.scheduler --once

test:
	docker compose exec backend pytest -q

lint:
	docker compose exec backend ruff check app tests

openapi:
	docker compose exec backend python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > contracts/openapi.json

logs:
	docker compose logs -f backend worker
