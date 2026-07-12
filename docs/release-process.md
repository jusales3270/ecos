# Release Process

## Versioning

A versão única fica em `VERSION`. Backend lê esse arquivo por `ecos.version.application_version()`. Frontend deve manter `package.json` e `package-lock.json` alinhados ao mesmo valor.

Política inicial: SemVer com sufixo RC, por exemplo `0.1.0-rc.1`.

## Release Candidate Checklist

1. Atualizar `VERSION`, `backend/pyproject.toml`, `frontend/package.json` e `frontend/package-lock.json`.
2. Atualizar `CHANGELOG.md`.
3. Rodar validação backend:
   ```bash
   cd backend
   uv sync
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest
   ```
4. Rodar validação frontend:
   ```bash
   cd frontend
   npm ci
   npm run lint
   npm run typecheck
   npm run test
   npm run build
   ```
5. Rodar PostgreSQL:
   ```bash
   cd backend
   uv run alembic upgrade head
   uv run alembic downgrade -1
   uv run alembic upgrade head
   ```
6. Rodar Docker:
   ```bash
   docker compose config
   docker compose build
   docker compose up -d
   curl -fsS http://127.0.0.1:8000/health/live
   curl -fsS http://127.0.0.1:8000/health/ready
   curl -fsS http://127.0.0.1:8000/health/version
   docker compose down
   ```
7. Rodar auditorias:
   ```bash
   make backend-audit
   make frontend-audit
   make secret-scan
   ```

## Tag

O Codex não cria tag. Após validação humana:

```bash
git tag -a v0.1.0-rc.1 -m "ECOS 0.1.0-rc.1"
git push origin v0.1.0-rc.1
```

## Build de Imagem

```bash
docker build \
  --build-arg ECOS_VERSION="$(cat VERSION)" \
  --build-arg ECOS_BUILD_COMMIT_SHA="$(git rev-parse HEAD)" \
  --build-arg ECOS_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t ecos:$(cat VERSION) .
```

## Rollback

1. Pausar tráfego.
2. Confirmar backup antes do rollback.
3. Restaurar imagem anterior.
4. Se necessário, aplicar downgrade Alembic documentado.
5. Validar `/health/ready`, login, sessão operacional, eventos, auditoria e outbox.

Nenhuma publicação, tag, deploy ou auto-merge é feito automaticamente.
