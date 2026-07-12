.PHONY: backend-sync backend-lint backend-format-check backend-test backend-audit frontend-install frontend-lint frontend-typecheck frontend-test frontend-build frontend-audit secret-scan test docker-config docker-build up down logs health migrations

backend-sync:
	cd backend && uv sync

backend-lint:
	cd backend && uv run ruff check .

backend-format-check:
	cd backend && uv run ruff format --check .

backend-test:
	cd backend && uv run pytest

backend-audit:
	cd backend && uvx pip-audit --strict --progress-spinner off

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

frontend-audit:
	cd frontend && npm audit --audit-level=critical

secret-scan:
	! git grep -n -E -e '-----BEGIN ((RSA|DSA|EC|OPENSSH) )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|xox[baprs]-|ghp_[A-Za-z0-9_]{36,}' -- ':!frontend/package-lock.json'

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
