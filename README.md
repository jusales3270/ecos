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

O fluxo cognitivo executável está em `backend/src/ecos/runtime/`. O Runtime cria a Session, solicita um `CognitivePlan` ao Planner e delega a execução coordenada ao Orchestrator real. O endpoint `POST /runtime/demo` preserva o mesmo contrato público e executa por padrão sem IA, banco de dados, embeddings, provedores reais ou chamadas externas.

## AI Provider Abstraction

A AI Provider Abstraction está em `backend/src/ecos/providers/` e mantém os Engines desacoplados de SDKs externos. O provider OpenAI usa o SDK oficial e a Responses API para geração de texto; `fake` continua sendo o padrão, inclusive para testes e para o runtime demo. Com `ECOS_AI_PROVIDER=openai`, o Container ativa as implementações provider-backed de Reasoning, Debate, War/Simulation e Decision Support, sempre por injeção do contrato genérico `AIProvider`.

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

O Orchestrator real está em `backend/src/ecos/orchestrator/` e consome um `CognitivePlan` imutável para coordenar Engines injetados por contrato genérico. Ele valida identidade de Plan/Session/Organization, dependências do DAG, engines registrados, timeouts, retries, condições estruturadas, governança e aprovação humana antes de invocar qualquer executor.

O Planner define como pensar; o Orchestrator apenas coordena o plano; os Engines realizam cognição. O Orchestrator não cria hipóteses, não recomenda, não decide, não aprova, não chama LLM, não importa OpenAI, não depende de `AIProvider`, não acessa Container, ambiente, PostgreSQL ou SQLAlchemy, e não persiste estado próprio.

São suportados modos sequencial, paralelo e condicional. A execução paralela usa limite de concorrência injetado e consolida resultados pela ordem do plano. Condições aceitam somente operadores allowlisted e fontes seguras, sem linguagem livre ou `eval`. Timeouts usam política injetada; retries só ocorrem quando o estágio permite, a falha é recuperável e o limite de tentativas não foi atingido, com backoff injetado.

Falhas de estágios obrigatórios interrompem dependentes e produzem `FailureReport` seguro. Estágios opcionais só viram `skipped` quando a política permite. Execution permanece bloqueado sem Governance satisfeita e aprovação humana explícita compatível com `organization_id`, `session_id` e `plan_id`; ausência de aprovação retorna estado `waiting_approval` retomável, preservando outputs já concluídos e timeline append-only.

## Governance Engine

O Governance Engine real está em `backend/src/ecos/governance/` e valida se a cognição pode prosseguir. Ele não raciocina sobre o problema, não gera hipóteses, não cria recomendação, não toma decisão empresarial, não chama LLM, não acessa banco, não acessa ambiente, não conhece o Container e não executa ações externas. Todas as dependências entram por injeção: `PolicyProvider`, `ApprovalPolicyProvider`, `IdentityPort`, `EventService`, relógio, gerador de IDs e configuração imutável.

Políticas organizacionais são imutáveis, versionadas, escopadas por `organization_id` e selecionadas de forma determinística por vigência, status `active`, ação aplicável, prioridade, `policy_id` e versão. Políticas expiradas, ausentes ou versões ativas ambíguas não são ignoradas. Regras usam somente operadores estruturados allowlisted (`equals`, comparações numéricas, `in`, `contains`, `exists`, `all`, `any`, `not` e equivalentes negativos), sem `eval`, templates executáveis ou linguagem arbitrária.

O resultado inclui `ComplianceReport`, `ExplainabilityReport`, violações seguras, autorização escopada por Organization, Session, Plan e ação, requisitos de aprovação, request de aprovação quando necessário e audit trail append-only em memória para persistência futura. Explainability exige objetivo, evidência, resumo de raciocínio, assumptions, riscos, alternativas, confidence 0–1, lacunas e recomendação; o Engine valida presença, estrutura e rastreabilidade básica, não a qualidade intelectual do raciocínio.

Os níveis oficiais de aprovação são Level 1 a Level 5. Level 1 pode autorizar automaticamente continuidade cognitiva de baixo risco e baixo impacto, mas não autoriza execução externa. Execution sempre exige autorização válida e aprovação humana explícita quando solicitada. Requests de aprovação passam pelos estados `pending`, `partially_approved`, `granted`, `rejected`, `expired`, `revoked` e `cancelled`; uma pessoa não conta duas vezes, papéis e quorum são validados, rejeição bloqueia e revogação invalida autorização dependente. A autenticação real não foi implementada: o `IdentityPort` consome uma identidade previamente validada por uma porta injetada.

O Runtime continua delegando ao Orchestrator. O Orchestrator invoca Governance como estágio do plano, preserva o `GovernanceResult`, entra em `waiting_approval` quando houver aprovação pendente e não transforma pending em granted. `/runtime/demo` continua retornando `status="completed"`, `recommendation="Proceed using ECOS context, reasoning, debate and governance."` e `confidence=0.91`, sem simular aprovação humana ou executar ação externa.

## Execution Layer

A Execution Layer real está em `backend/src/ecos/execution/` e transforma uma ação aprovada em operação controlada. Ela não decide, não recomenda, não altera `CognitivePlan`, `DecisionPackage` ou `GovernanceResult`, não concede aprovação e não acessa LLM, `AIProvider`, Container, variáveis de ambiente, SQLAlchemy, PostgreSQL ou sistemas externos diretamente.

Toda comunicação operacional passa por `ExecutionConnector` registrado em `ConnectorRegistry` injetado. A seleção é determinística por `connector_id`, fallback explicitamente permitido, capability autorizada, prioridade e `connector_id`; conectores indisponíveis, incompatíveis ou fora da autorização são rejeitados. A configuração padrão registra apenas um connector em memória para dry-run, sem ERP, CRM, APIs reais, navegador, agentes ou MCP reais.

Os contratos tipados cobrem execuções `human`, `system`, `api`, `agent`, `browser` e `mcp`, `ExecutionPlan` com DAG validado, constraints, recursos, janela, timeout, retry, fallback autorizado, artifacts por referência, métricas, logs seguros, timeline append-only, falhas classificadas, idempotência em memória e rollback explícito. `dry_run` é o padrão; `live` exige autorização explícita e connector com suporte a live.

Human execution cria `HumanTask` em memória e retorna `paused` com `ExecutionResumeState`; não finge conclusão. Rollback nunca é inventado: roda em ordem reversa apenas para etapas concluídas com `RollbackAction` explícita e autorização de rollback. Resultados, logs, timeline, artifacts, idempotência e estado de retomada ainda não são persistidos neste sprint.

## Cognitive Planner

O Cognitive Planner real está em `backend/src/ecos/planner/` e planeja como o E.C.O.S. deverá pensar antes do Context Engine. Ele cria um `CognitivePlan` tipado, imutável e explicável com classificação do objetivo, complexidade, risco, estratégia cognitiva, Engines, especialistas, dependências, estimativas relativas, meta de confiança e requisitos de governança.

O Planner usa somente regras determinísticas e dependências internas injetadas pelo Container: `SpecialistRegistry`, `EventService`, relógio e gerador de IDs. Ele não usa LLM, não importa OpenAI, não depende de `AIProvider`, não raciocina sobre o problema, não recomenda, não decide, não executa Engines e não altera memória ou políticas. Execução, quando solicitada, aparece apenas como estágio condicional bloqueado até governança e aprovação humana.

As estimativas são provider-agnostic; `estimated_cost_units` é custo relativo, não preço monetário. O Orchestrator consome o plano validado sem mutá-lo, sem reconstruir regras do Planner e sem recalcular complexidade, risco ou especialistas. Nunca versione segredos.

## Decision Support Engine

O Decision Support Engine está em `backend/src/ecos/decision/` e preserva a implementação determinística quando `ECOS_AI_PROVIDER=fake`, mantendo o resultado público de `/runtime/demo`. Com `ECOS_AI_PROVIDER=openai`, o Container recupera o provider pelo `ProviderRegistry` e injeta `AIDecisionSupportEngine`, que depende somente do contrato `AIProvider`.

O Engine consolida Context, Reasoning Report, Debate Report e Simulation Report em uma recomendação executiva estruturada e explicável. Ele não decide, não aprova, não autoriza execução e não substitui governança ou liderança. `required_approvals` representa requisitos sugeridos para avaliação humana, não aprovações concedidas. Qualquer execução posterior exige governança e autorização fora deste Engine. Prompts e respostas completas não são persistidos, e chamadas externas só ocorrem quando OpenAI é explicitamente configurada com credencial local.

## Debate Engine

O Debate Engine preserva a implementação determinística quando `ECOS_AI_PROVIDER=fake`. Com `openai`, o Container resolve o provider pelo `ProviderRegistry` e o injeta no `AIDebateEngine`. Tanto Reasoning quanto Debate dependem somente do contrato genérico `AIProvider`; somente a camada de providers conhece o SDK. O Debate avalia o relatório de raciocínio e todas as contribuições independentes dos especialistas, preserva divergências, conflitos e perguntas abertas e não toma decisões nem autoriza execução. Chamadas externas só ocorrem quando OpenAI é configurada explicitamente, e nenhum segredo deve ser versionado.

## War / Simulation Engine

O modo `fake`, que continua sendo o padrão, usa a simulação determinística e preserva o resultado público de `/runtime/demo`. Com `ECOS_AI_PROVIDER=openai`, o Container recupera o provider exclusivamente pelo `ProviderRegistry` e o injeta no `AIWarEngine`, assim como faz com Reasoning e Debate. Esses Engines dependem somente de `AIProvider`; apenas a camada de providers conhece o SDK OpenAI. O War Engine explora futuros possíveis, inclusive cenários desfavoráveis, riscos, oportunidades, efeitos e contingências: ele não prevê o futuro, não decide, não aprova e não autoriza execução. A decisão permanece humana. Chamadas externas só ocorrem quando OpenAI e a credencial local são configuradas explicitamente. Nunca versione segredos.

## Specialist Framework

A arquitetura inicial do Specialist Framework está em `backend/src/ecos/specialists/` e define modelos, interface de provider, registry e serviço de orquestração por abstração. Os especialistas continuam papéis cognitivos independentes: não recebem `AIProvider` e não se comunicam diretamente entre si.

## Reasoning Engine

O Reasoning Engine mantém a implementação determinística quando `ECOS_AI_PROVIDER=fake`,
que continua sendo o padrão e preserva o resultado público do runtime demo. Ao selecionar
`openai`, o Container resolve o provider pelo `ProviderRegistry` e o injeta no
`AIReasoningEngine`. O Engine conhece somente o contrato genérico `AIProvider`: não importa
o SDK, não lê chaves e não instancia nem seleciona providers. Respostas são aceitas somente
como JSON estruturado validado, sem solicitar ou persistir cadeia privada de pensamento.

## Context Engine

O Context Engine real está em `backend/src/ecos/context/` e monta um Unified Context tipado a partir do objetivo, dados da sessão, restrições, políticas, recursos, sinais externos fornecidos e memória organizacional. Ele não usa LLM, não importa OpenAI, não depende de `AIProvider`, não recomenda, não raciocina e não executa ações.

A seleção é feita exclusivamente pelo Container: com `ECOS_MEMORY_REPOSITORY=fake`, o runtime demonstrativo preserva `FakeContextProvider` e mantém o comportamento público de `/runtime/demo`; com `ECOS_MEMORY_REPOSITORY=postgres`, o Container injeta `ContextEngine` com o `MemoryRepository` configurado. A recuperação de memória é sempre escopada por `organization_id`, mantém referências aos objetos originais e rejeita qualquer memória retornada de outra organização.

Relevância, confiança e completude são calculadas de forma determinística e testável. A relevância considera correspondência com objetivo, entidades, políticas/restrições, tipo/importância da memória, confiança e recência, sem embeddings, pgvector, busca web, Knowledge Graph ou chamadas externas. Lacunas de contexto permanecem explícitas em `missing_context`; elas reduzem `confidence` e `completeness` em vez de serem ocultadas.

## Memory Engine

O Memory Engine preserva o contrato `MemoryRepository` e oferece persistência em PostgreSQL via SQLAlchemy 2 e asyncpg. O fake continua como padrão; defina `ECOS_MEMORY_REPOSITORY=postgres` para persistência permanente e para ativar o Context Engine real no Container. Memórias podem carregar `organization_id`; o Context Engine exige esse escopo para recuperar contexto sem vazamento entre organizações. Este estágio não implementa pgvector, busca vetorial, embeddings ou LLM.

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
