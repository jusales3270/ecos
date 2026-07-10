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

## Context Engine

A arquitetura inicial do Context Engine está em `backend/src/ecos/context/` e define apenas modelos, interface de provider e serviço de orquestração por abstração. Esta camada ainda não implementa banco de dados, Knowledge Graph, busca vetorial ou LLM.

## Memory Engine

A arquitetura inicial do Memory Engine está em `backend/src/ecos/memory/` e define apenas modelos, interface de repositório e serviço de orquestração por abstração. Esta camada ainda não implementa PostgreSQL, pgvector, busca vetorial, embeddings ou LLM.

## Backend

O backend inicial do ECOS usa Python 3.12, FastAPI, pydantic-settings, pytest, Ruff e uv para gerenciamento de dependências.

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

### Executar lint e formatação

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
```
