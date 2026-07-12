.PHONY: backend-sync backend-lint backend-format-check backend-test frontend-install frontend-lint frontend-typecheck frontend-test frontend-build test docker-config docker-build up down logs health migrations

backend-sync:
	cd backend && uv sync

backend-lint:
	cd backend && uv run ruff check .

backend-format-check:
	cd backend && uv run ruff format --check .

backend-test:
	cd backend && uv run pytest

frontend-install:
	cd frontend && npm ci

frontend-lint:
	cd frontend && npm run lint

frontend-typecheck:
	cd frontend && npm run typecheck

frontend-test:
	cd frontend && npm run test

frontend-build:
	cd frontend && npm run build

test: backend-lint backend-format-check backend-test frontend-lint frontend-typecheck frontend-test frontend-build

docker-config:
	docker compose config

docker-build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f app

migrations:
	docker compose run --rm migrations

health:
	curl -fsS http://127.0.0.1:8000/health/live
	curl -fsS http://127.0.0.1:8000/health/ready
	curl -fsS http://127.0.0.1:8000/health/version
