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

Com `ECOS_MEMORY_REPOSITORY=fake`, o Container mantém `FakeContextProvider` para o runtime demo. Com `ECOS_MEMORY_REPOSITORY=postgres`, o Container injeta o Context Engine real, que constrói contexto somente a partir da requisição da sessão e da memória organizacional escopada por `organization_id`. O Context Engine não usa LLM, OpenAI, embeddings, pgvector, busca web ou Knowledge Graph; ele calcula relevância, confiança e completude de forma determinística e mantém lacunas explícitas em `missing_context`.

## Cognitive Planner local

O Container registra o `CognitivePlanner` real por padrão e injeta `SpecialistRegistry`, `EventService`, relógio UTC e gerador de identificadores. O Planner roda antes do Context Engine, emite eventos seguros de planejamento e gera um `CognitivePlan` determinístico com Engines, especialistas, dependências acíclicas, governança, aprovação humana requerida quando necessário, estimativas relativas e `confidence_target`.

O Planner não usa OpenAI, `AIProvider`, variáveis de ambiente, PostgreSQL ou Container internamente. Ele não raciocina, não recomenda, não decide e não executa ações. O runtime demo preserva o mesmo resultado público; o Orchestrator definitivo consumirá o plano completo em sprint futura.

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
falha com uma mensagem de configuração clara. Essa seleção ativa os Engines
provider-backed de Reasoning, Debate, War e Decision Support; o Container resolve e
injeta o provider pelo registry, enquanto os Engines dependem somente de `AIProvider`
e permanecem independentes da OpenAI e do SDK. O Debate recebe as contribuições
independentes dos especialistas, preserva divergências e não toma decisões. O
Decision Support consolida Context, Reasoning, Debate e Simulation em recomendação
executiva para avaliação humana: ele não decide, não aprova e não autoriza execução.
`required_approvals` representa requisitos sugeridos, não aprovações concedidas.
Chamadas reais só ocorrem com OpenAI explicitamente selecionada e configurada. O
`/health` faz uma verificação controlada do modelo configurado e nunca retorna chaves,
headers, prompts ou respostas. Não coloque chaves nos arquivos `.env.example` nem em
arquivos versionados.

O War Engine recebe contexto, memória do ciclo e os relatórios completos de Reasoning e Debate. Ele explora cenários possíveis — incluindo worst case e black swan — sem suprimir riscos desfavoráveis e sem apresentar a simulação como previsão. A decisão, aprovação e autorização de execução permanecem humanas. O modo `fake` continua determinístico, não exige credenciais e não realiza chamadas externas.

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

`ECOS_SESSION_REPOSITORY` e `ECOS_MEMORY_REPOSITORY` podem ser configurados independentemente como `fake` ou `postgres`; ambos usam `fake` por padrão. Quando memória PostgreSQL está ativa, cada consulta de contexto é restrita ao `organization_id`; falhas de memória e retornos de outra organização são erros explícitos, sem fallback silencioso.

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

Esse comando habilita os testes condicionais dos repositórios PostgreSQL de sessões e memórias. A migration `20260711_02` cria `memories` após a migration de sessões, e `20260711_03` adiciona o índice de escopo organizacional para memórias; elas podem ser validadas com `alembic downgrade base` e `alembic upgrade head`.
