# ECOS — Enterprise Cognitive Operating System

ECOS (Enterprise Cognitive Operating System) é uma plataforma voltada a ampliar a inteligência organizacional por meio de contexto, raciocínio, especialistas, debate, simulação, recomendação, governança, execução e aprendizado contínuo.

O objetivo do ECOS é servir como uma base estruturada para sistemas cognitivos empresariais capazes de organizar conhecimento, apoiar decisões, coordenar agentes especializados, avaliar alternativas e transformar aprendizado operacional em melhoria contínua.

## Stack inicial

- **Backend:** Python + FastAPI
- **Banco:** PostgreSQL + pgvector
- **Cache:** Redis
- **Frontend:** Next.js
- **Infra local:** Docker Compose

## Estrutura inicial do repositório

```text
docs/      Documentação funcional, técnica e arquitetural.
backend/   Serviços de backend e APIs.
frontend/  Interface web e experiência do usuário.
infra/     Infraestrutura local, containers e automações operacionais.
tests/     Testes automatizados e recursos de validação.
```

## Estado atual

Este repositório contém o baseline inicial de organização e um backend FastAPI mínimo com endpoint de health check.


## Domínio

O núcleo de domínio inicial está em `backend/src/ecos/domain/` e modela apenas entidades e enums com Pydantic v2. Esta camada ainda não implementa banco de dados, APIs, memória, LLMs ou lógica cognitiva.

## Runtime Demo

O primeiro fluxo cognitivo executável está em `backend/src/ecos/runtime/` e conecta os módulos arquitetados usando apenas implementações Fake/InMemory. O endpoint `POST /runtime/demo` executa o fluxo sem IA, banco de dados, embeddings, provedores reais ou chamadas externas.

## AI Provider Abstraction

A AI Provider Abstraction está em `backend/src/ecos/providers/` e mantém os Engines desacoplados de SDKs externos. O provider OpenAI usa o SDK oficial e a Responses API para geração de texto; `fake` continua sendo o padrão, inclusive para testes e para o runtime demo.

Para ativar a OpenAI, configure somente no ambiente local:

```bash
export ECOS_AI_PROVIDER=openai
export ECOS_OPENAI_API_KEY='sua-chave-local'
export ECOS_OPENAI_MODEL=gpt-4.1-mini
export ECOS_OPENAI_EMBEDDING_MODEL=text-embedding-3-small
export ECOS_OPENAI_TIMEOUT_SECONDS=30
export ECOS_OPENAI_MAX_RETRIES=2
```

Não versione a chave. Streaming, tools, web/file search, function calling e Realtime não são suportados neste estágio. O método contratual de embeddings está implementado no provider, mas não está integrado ao Memory Engine.

## Event Bus

A arquitetura inicial do Event Bus está em `backend/src/ecos/events/` e define apenas modelos, interface de barramento e serviço de comunicação por abstração. Esta camada ainda não implementa RabbitMQ, Kafka, Redis Pub/Sub, filas ou eventos reais.

## Cognitive Session Manager

O Cognitive Session Manager mantém seu contrato de repositório e oferece persistência de sessões, estado atual, snapshots e transições em PostgreSQL via SQLAlchemy 2 e asyncpg. O fake em memória permanece como padrão para testes e para o runtime demo. Defina `ECOS_SESSION_REPOSITORY=postgres` e aplique as migrations Alembic para habilitar PostgreSQL.

## Orchestrator

A arquitetura inicial do Orchestrator está em `backend/src/ecos/orchestrator/` e define apenas modelos, interface de provider e serviço de orquestração por abstração. Esta camada ainda não implementa execução real, filas, Temporal, Celery ou asyncio.

## Cognitive Planner

A arquitetura inicial do Cognitive Planner está em `backend/src/ecos/planner/` e define apenas modelos, interface de provider e serviço de orquestração por abstração. Esta camada ainda não implementa IA, heurísticas, planejamento automático, OpenAI ou Anthropic.

## Decision Support Engine

A arquitetura inicial do Decision Support Engine está em `backend/src/ecos/decision/` e define apenas modelos, interface de provider e serviço de orquestração por abstração. Esta camada ainda não implementa IA, prompts, OpenAI, Anthropic ou lógica de decisão.

## Debate Engine

A arquitetura inicial do Debate Engine está em `backend/src/ecos/debate/` e define apenas modelos, interface de provider e serviço de orquestração por abstração. Esta camada ainda não implementa IA, prompts, OpenAI, Anthropic ou lógica de consenso.

## Specialist Framework

A arquitetura inicial do Specialist Framework está em `backend/src/ecos/specialists/` e define apenas modelos, interface de provider, registry e serviço de orquestração por abstração. Esta camada ainda não implementa IA, prompts, OpenAI, Anthropic ou Debate.

## Reasoning Engine

O Reasoning Engine mantém a implementação determinística quando `ECOS_AI_PROVIDER=fake`,
que continua sendo o padrão e preserva o resultado público do runtime demo. Ao selecionar
`openai`, o Container resolve o provider pelo `ProviderRegistry` e o injeta no
`AIReasoningEngine`. O Engine conhece somente o contrato genérico `AIProvider`: não importa
o SDK, não lê chaves e não instancia nem seleciona providers. Respostas são aceitas somente
como JSON estruturado validado, sem solicitar ou persistir cadeia privada de pensamento.

## Context Engine

A arquitetura inicial do Context Engine está em `backend/src/ecos/context/` e define apenas modelos, interface de provider e serviço de orquestração por abstração. Esta camada ainda não implementa banco de dados, Knowledge Graph, busca vetorial ou LLM.

## Memory Engine

O Memory Engine preserva o contrato `MemoryRepository` e oferece persistência em PostgreSQL via SQLAlchemy 2 e asyncpg. O fake continua como padrão; defina `ECOS_MEMORY_REPOSITORY=postgres` para persistência permanente. Este estágio não implementa pgvector, busca vetorial, embeddings ou LLM.

## Learning Engine

O Learning Engine em `backend/src/ecos/learning/` é a fronteira obrigatória para criação ou atualização permanente de memória organizacional. Ele aplica uma política determinística (evidência presente e confiança mínima de `0.5`), preserva origem, evidência, confiança e sessão, publica os eventos de aprendizado existentes e só então entrega aprendizados aprovados ao Memory Engine. O runtime e os demais motores não gravam memória diretamente.

## Backend

O backend inicial do ECOS usa Python 3.12, FastAPI, pydantic-settings, pytest, Ruff e uv para gerenciamento de dependências. Para execução local com Docker Compose, PostgreSQL, Redis, pgAdmin e backend, consulte `docs/local-development.md`.

### Instalar dependências

```bash
cd backend
uv sync
```

### Executar localmente

```bash
cd backend
uv run uvicorn ecos.main:app --reload
```

### Verificar health check

```bash
curl http://127.0.0.1:8000/health
```

A resposta esperada contém `status`, `service` e `version`.

### Executar testes

```bash
cd backend
uv run pytest
```

Os testes PostgreSQL são condicionais. Para executá-los contra um banco descartável:

```bash
ECOS_TEST_DATABASE_URL=postgresql://ecos:ecos@localhost:5432/ecos uv run pytest
```

Um smoke test real da OpenAI existe apenas como opt-in e só executa quando as duas variáveis estão presentes:

```bash
ECOS_RUN_OPENAI_TESTS=1 ECOS_OPENAI_API_KEY='sua-chave-local' uv run pytest -k optional_real_openai
```

A suíte padrão usa cliente mockado e não realiza chamadas à OpenAI.

### Executar lint e formatação

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
```
