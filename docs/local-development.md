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

O fluxo demo preserva o mesmo resultado público e usa providers cognitivos Fake e, por padrão, repositórios em memória. O Runtime cria a Session, solicita o `CognitivePlan` e entrega Plan + Session ao Orchestrator real. O Orchestrator coordena Context, Reasoning, Specialists, Debate, Simulation, Decision Support e Learning por executors injetados; o resultado cognitivo passa pelo Learning Engine antes de virar memória.

Com `ECOS_MEMORY_REPOSITORY=fake`, o Container mantém `FakeContextProvider` para o runtime demo. Com `ECOS_MEMORY_REPOSITORY=postgres`, o Container injeta o Context Engine real, que constrói contexto somente a partir da requisição da sessão e da memória organizacional escopada por `organization_id`. O Context Engine não usa LLM, OpenAI, embeddings, pgvector, busca web ou Knowledge Graph; ele calcula relevância, confiança e completude de forma determinística e mantém lacunas explícitas em `missing_context`.

## Cognitive Planner local

O Container registra o `CognitivePlanner` real por padrão e injeta `SpecialistRegistry`, `EventService`, relógio UTC e gerador de identificadores. O Planner roda antes do Context Engine, emite eventos seguros de planejamento e gera um `CognitivePlan` determinístico com Engines, especialistas, dependências acíclicas, governança, aprovação humana requerida quando necessário, estimativas relativas e `confidence_target`.

O Planner não usa OpenAI, `AIProvider`, variáveis de ambiente, PostgreSQL ou Container internamente. Ele não raciocina, não recomenda, não decide e não executa ações. O runtime demo preserva o mesmo resultado público; o Orchestrator real consome o plano completo sem mutá-lo.

## Orchestrator local

O Container registra o Orchestrator real por padrão e injeta registry de executors, `EventService`, `SessionService`, relógio UTC, gerador de IDs, sleeper/backoff e configuração imutável de concorrência. O Runtime não chama Engines cognitivos diretamente; ele delega a execução ao Orchestrator e retorna o resultado público de `/runtime/demo`.

O Orchestrator valida o DAG do `CognitivePlan`, resolve dependências, executa estágios prontos em modo sequencial, paralelo ou condicional, preserva outputs intermediários, sincroniza Session e registra timeline append-only. Condições usam somente operadores estruturados allowlisted; não há `eval`, expressão Python ou código recebido. Timeouts e retries são controlados por política injetada, com backoff testável sem espera real.

Falhas obrigatórias interrompem dependentes e produzem relatório seguro; falhas opcionais podem virar `skipped` somente quando o plano permite. Execution permanece subordinado à governança humana: sem Governance satisfeita e aprovação explícita compatível, o pipeline fica em `waiting_approval` com estado retomável e sem marcar falha apenas por aguardar decisão humana.

O Orchestrator não realiza cognição, não chama LLM, não importa OpenAI, não depende de `AIProvider`, não acessa Container, variáveis de ambiente, PostgreSQL ou SQLAlchemy, não persiste estado próprio e não modifica o `CognitivePlan`.

## Governance local

O Container registra o `GovernanceEngine` real e injeta `PolicyProvider`, `ApprovalPolicyProvider`, `IdentityPort`, `EventService`, relógio, gerador de IDs e `GovernanceConfig`. O Engine valida se a cognição pode prosseguir; ele não raciocina, não altera recomendações, não concede aprovação humana, não acessa PostgreSQL, não persiste auditoria e não executa ações externas.

Políticas são versionadas, imutáveis e selecionadas de forma determinística somente quando estão `active` e vigentes. Regras são estruturadas e usam operadores allowlisted; não há `eval`, código dinâmico ou linguagem arbitrária. A avaliação produz `ComplianceReport`, `ExplainabilityReport`, `PolicyViolation`, `AuthorizationDecision`, `ApprovalRequest` quando necessário e `AuditRecord` append-only em memória. O audit trail ainda não é persistido.

Os níveis de aprovação são Level 1 a Level 5. Level 1 pode liberar continuidade cognitiva de baixo risco e baixo impacto, mas execução externa sempre exige aprovação humana explícita. Estados de aprovação incluem `pending`, `partially_approved`, `granted`, `rejected`, `expired`, `revoked` e `cancelled`. Papéis, aprovadores distintos, quorum, rejeição, expiração e revogação são validados pelo Engine com uma identidade previamente validada pelo `IdentityPort`; login, JWT, OAuth e autenticação real não pertencem a esta sprint.

O Runtime não chama Governance diretamente. Ele continua delegando ao Orchestrator, que executa o estágio `governance`, preserva o `GovernanceResult` e pausa em `waiting_approval` quando aprovação humana é obrigatória. A retomada usa estado retornável e decisão humana explícita, preservando outputs e timeline já concluídos. Execution real só executa um `ExecutionRequest` estruturado com autorização compatível; autorização ausente, negada, expirada, revogada ou fora de Organization, Session, Plan e escopo é rejeitada.

O `/runtime/demo` usa uma política determinística segura de continuidade, não solicita execução externa, não simula aprovação humana e preserva o resultado público: `status` igual a `completed`, recomendação `Proceed using ECOS context, reasoning, debate and governance.` e `confidence` `0.91`.

## Execution local

O Container registra `ExecutionEngine`, `ConnectorRegistry`, `InMemoryIdempotencyProvider`, `InMemoryHumanTaskProvider`, relógio UTC, gerador de IDs, sleeper/backoff e apenas connector em memória por padrão. A Execution Layer coordena somente as etapas internas de um `ExecutionPlan` aprovado; o Orchestrator continua coordenando o `CognitivePlan`.

`dry_run` é o modo padrão e não produz efeito externo. `live` exige autorização explícita e connector com suporte a execução real; nenhum connector real de ERP, CRM, API HTTP, navegador, agente externo ou MCP foi adicionado nesta sprint. A suíte padrão usa somente conectores em memória, não exige PostgreSQL e não realiza chamadas externas.

O plano operacional é imutável, tipado e validado como DAG: IDs e ordens únicos, dependências existentes e anteriores, sem ciclos, timeouts positivos, retry válido, parâmetros seguros e rollback somente quando declarado. Preconditions e validation rules usam operadores estruturados allowlisted, sem `eval`, `exec`, templates executáveis ou linguagem livre.

Idempotência é em memória e usa fingerprint criptográfico determinístico sobre payload seguro. A mesma chave com o mesmo fingerprint retorna resultado anterior; a mesma chave com payload diferente gera conflito; retries reutilizam o escopo idempotente da etapa. Human execution cria tarefa humana e retorna `paused` com estado retomável. Rollback roda em ordem reversa apenas para etapas concluídas com ação de rollback explícita e autorização compatível.

Artifacts são referências tipadas, não binários no resultado. Métricas, logs seguros e timeline são produzidos no `ExecutionResult`, ainda sem persistência. `/runtime/demo` permanece sem etapa externa de Execution e mantém exatamente o contrato público existente.

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
