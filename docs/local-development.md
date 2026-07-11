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

O fluxo demo preserva o mesmo resultado público e usa providers cognitivos Fake e, por padrão, repositórios em memória. O resultado cognitivo passa pelo Learning Engine antes de virar memória.

## Provider OpenAI opcional

O provider de IA padrão é `fake`, portanto a instalação e a suíte padrão não precisam de credenciais nem fazem chamadas externas. Para selecionar o adaptador OpenAI no Container:

```bash
cd backend
export ECOS_AI_PROVIDER=openai
export ECOS_OPENAI_API_KEY='sua-chave-local'
export ECOS_OPENAI_MODEL=gpt-4.1-mini
export ECOS_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
export ECOS_OPENAI_TIMEOUT_SECONDS=30
export ECOS_OPENAI_MAX_RETRIES=2
uv run uvicorn ecos.main:app --reload
```

Se `ECOS_AI_PROVIDER=openai` for definido sem `ECOS_OPENAI_API_KEY`, a inicialização
falha com uma mensagem de configuração clara. Essa seleção também ativa os Engines de
Reasoning e Debate provider-backed; o Container resolve e injeta o provider pelo registry,
enquanto os Engines permanecem independentes da OpenAI e do SDK. O Debate recebe as
contribuições independentes dos especialistas, preserva divergências e não toma decisões.
Chamadas reais só ocorrem com OpenAI
explicitamente selecionada e configurada. O `/health` faz uma verificação controlada do
modelo configurado e nunca retorna chaves, headers, prompts ou respostas. Não coloque
chaves nos arquivos `.env.example` nem em arquivos versionados.

O provider usa Responses API sem streaming, tools, buscas ou function calling. Embeddings atendem somente ao contrato do provider e não são conectados ao Memory Engine. O teste real é opcional:

```bash
ECOS_RUN_OPENAI_TESTS=1 ECOS_OPENAI_API_KEY='sua-chave-local' uv run pytest -k optional_real_openai
```

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
