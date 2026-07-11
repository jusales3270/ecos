# ECOS — execução local

Este guia prepara o ECOS para execução em ambiente de desenvolvimento usando serviços locais e configurações sem segredos reais.

## Docker Compose

```bash
docker compose up
```

O Compose sobe `postgres:16`, `redis:7`, `backend` e `pgadmin` em uma rede única, com volumes persistentes e healthchecks.

## Backend com uv

Crie o arquivo local de ambiente a partir do modelo versionado:

```bash
cp backend/.env.example backend/.env
```

Em seguida, instale dependências e execute a aplicação:

```bash
cd backend
uv sync
uv run uvicorn ecos.main:app --reload
```

## Endpoints úteis

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/health
```

## Runtime demo

```bash
curl -X POST http://127.0.0.1:8000/runtime/demo \
  -H 'Content-Type: application/json' \
  -d '{"objective":"Improve organizational decision quality"}'
```

O fluxo demo usa providers Fake e, por padrão, repositórios em memória. O resultado cognitivo passa pelo Learning Engine antes de virar memória. Não há IA real, embeddings ou chamadas externas.

## Persistência de sessões no PostgreSQL

O repositório fake é o padrão. Para usar PostgreSQL no container da aplicação:

```bash
cd backend
export ECOS_DATABASE_URL=postgresql://ecos:ecos@localhost:5432/ecos
export ECOS_SESSION_REPOSITORY=postgres
export ECOS_MEMORY_REPOSITORY=postgres
uv run alembic upgrade head
uv run uvicorn ecos.main:app --reload
```

`ECOS_SESSION_REPOSITORY` e `ECOS_MEMORY_REPOSITORY` podem ser configurados independentemente como `fake` ou `postgres`; ambos usam `fake` por padrão.

Para reverter todas as migrations:

```bash
cd backend
uv run alembic downgrade base
```

Os testes de integração ficam ignorados sem configuração. Use um banco descartável e execute:

```bash
cd backend
ECOS_TEST_DATABASE_URL=postgresql://ecos:ecos@localhost:5432/ecos uv run pytest
```

Esse comando habilita os testes condicionais dos repositórios PostgreSQL de sessões e memórias. A migration `20260711_02` cria `memories` após a migration de sessões; ela pode ser validada isoladamente com `alembic downgrade 20260711_01` e `alembic upgrade head`.
