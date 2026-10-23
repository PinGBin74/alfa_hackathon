.PHONY: up down build seed seed-demo ingest warmup test lint openapi logs frontend-dev

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

seed:
	docker compose exec backend python -m app.db.seed

# без исходных данных кейса: синтетические компании, платежи и демо-новости с разметкой (data/synthetic)
seed-demo:
	docker compose exec backend python -m app.db.seed --dir data/synthetic --news data/synthetic/news.jsonl

ingest:
	docker compose exec backend python -m app.ingestion.scheduler --once

# заранее подготовить разборы по верху ленты тестовых пользователей (~0,8 ₽ за разбор)
warmup:
	docker compose exec backend python -m app.agent.warmup --top 2

test:
	docker compose exec backend pytest -q

lint:
	docker compose exec backend ruff check app tests

openapi:
	docker compose exec backend python -c "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))" > contracts/openapi.json

logs:
	docker compose logs -f backend worker

# разработка фронтенда без Docker: Vite на :3000, /api -> http://127.0.0.1:8000
frontend-dev:
	cd frontend && npm ci && npm run dev
