# ECOS — Enterprise Cognitive Operating System

ECOS (Enterprise Cognitive Operating System) é uma plataforma voltada a ampliar a inteligência organizacional por meio de contexto, raciocínio, especialistas, debate, simulação, recomendação, governança, execução e aprendizado contínuo.

O objetivo do ECOS é servir como uma base estruturada para sistemas cognitivos empresariais capazes de organizar conhecimento, apoiar decisões, coordenar agentes especializados, avaliar alternativas e transformar aprendizado operacional em melhoria contínua.

## Stack operacional

- **Backend:** Python + FastAPI
- **Banco:** PostgreSQL opcional
- **Cache:** Redis
- **Frontend:** React + TypeScript + Vite + React Router
- **Infra local:** Docker Compose com PostgreSQL, migrations e aplicação

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

A arquitetura de eventos está em `backend/src/ecos/events/` e a infraestrutura persistente de eventos, auditoria e observabilidade está em `backend/src/ecos/observability/`. Eventos representam fatos imutáveis: correções geram novos eventos com nova identidade e, quando aplicável, `causation_id`; eventos históricos não são atualizados, substituídos ou apagados pelo Event Store.

O `EventService` central valida, aplica redaction, calcula fingerprint SHA-256 determinístico, persiste no `EventStore`, aciona projectors e só depois publica no `EventBus`. O modo padrão usa `InMemoryEventStore`, `InMemoryAuditRepository` e `InMemoryObservabilityRepository`, sem arquivo, banco ou estado global entre testes. PostgreSQL é opcional via `ECOS_OBSERVABILITY_REPOSITORY=postgres` e reutiliza `ECOS_DATABASE_URL`, SQLAlchemy async e Alembic existentes, sem banco separado e sem fallback silencioso.

Consultas de eventos são escopadas por `organization_id` e podem filtrar por Session, `correlation_id`, tipo, categoria, fonte, tempo e sequência. A ordenação padrão é `stored_sequence`, `occurred_at`, `event_id`. Replay suporta `read_only` e `safe_projection`: ele não repersiste eventos, não publica no bus, não executa Execution, Connectors, notificações ou ações empresariais, e só chama projectors marcados como replay-safe.

Audit trail persistente é projetado de eventos auditáveis de Governance, Execution, Observation, Learning, Memory e Session. A integridade usa fingerprint determinístico individual e é documentada como tamper-evident, não tamper-proof. Métricas técnicas/cognitivas, logs estruturados seguros, traces/spans por `correlation_id`, health snapshots e alert signals são derivados de fatos; alertas são armazenados, mas não enviados por e-mail, Slack, webhook ou serviço externo. Eventos internos de observabilidade não criam cadeia recursiva infinita: o `EventService` usa projectors e registros internos em vez de emitir/persistir `EVENT_STORED` sobre si mesmo.

Observation Engine e Observability Layer têm responsabilidades distintas. Observation Engine mede resultados organizacionais declarados. Observability Layer mede o funcionamento técnico e cognitivo do E.C.O.S. O Sprint 17D não implementou OII, dashboards, tracing vendor, Prometheus/Grafana/Datadog/Sentry ou filas distribuídas; autenticação e RBAC locais foram adicionados no Sprint 17F.

## Segurança, autenticação e multitenancy

A camada de segurança local está em `backend/src/ecos/security/` e adiciona identidade, autenticação, autorização e isolamento organizacional sem provedor externo. O modo padrão usa `InMemorySecurityRepository`; PostgreSQL é ativado somente com `ECOS_SECURITY_REPOSITORY=postgres`, reutilizando `ECOS_DATABASE_URL` e as migrations Alembic.

O modelo explícito inclui usuário, organização, vínculo usuário-organização, papéis, permissões, credencial de senha, sessão de autenticação, principal autenticado e `SecurityContext`. O contexto autenticado carrega `user_id`, `organization_id`, `roles`, `permissions`, `authentication_method`, `session_id`/`token_id`, `issued_at`, `expires_at` e `correlation_id`. Quando existe identidade autenticada, serviços escopados derivam `organization_id` do principal e não aceitam sobrescrita por body, query string ou payload do cliente.

A autenticação é local e determinística. Senhas são armazenadas com Argon2id via `argon2-cffi`; tokens Bearer são JWT HS256 via `PyJWT`, assinados com `ECOS_AUTH_TOKEN_SECRET`, com `iss`, `aud`, `sub`, `org`, `sid`, `jti`, `iat` e `exp`. Tokens inválidos, expirados, revogados ou adulterados retornam 401. Produção não inicia com o segredo de desenvolvimento; configure um segredo forte em `ECOS_AUTH_TOKEN_SECRET`.

RBAC usa papéis organizacionais: `viewer`, `operator`, `manager`, `executive`, `executive_board`, `auditor`, `admin` e `global_admin`. Permissões são explícitas para configurações organizacionais, sessões, memória, Knowledge Graph, eventos/auditoria, decisões, governança, execução, observação, aprendizado e administração. `admin` é administrador da própria organização; capacidades globais ficam separadas em `global_admin`.

Eventos de segurança são persistidos como fatos append-only e projetados para auditoria/observability: autenticação bem-sucedida/falha, acesso negado, tentativa cross-tenant, criação/revogação de sessão, mudança de papel/permissão e execução privilegiada. A redação central remove headers de autorização, cookies, senhas, tokens, API keys, secrets, credenciais e chaves privadas de payloads, logs, auditoria e observability.

O isolamento organizacional é aplicado por `organization_id` nos repositórios e nos wrappers escopados de Session e Memory. Knowledge Graph, Event Store, Audit Trail e Observability já consultam por organização obrigatória; traversals, buscas e queries não atravessam organizações. IDs conhecidos de outro tenant geram falha segura em vez de fallback silencioso.

`/auth/login` autentica senha local e retorna Bearer token. `/security/me` exige Bearer token válido. Ausência ou falha de credencial retorna 401 com `WWW-Authenticate: Bearer`; permissão insuficiente ou acesso cross-tenant retorna 403. `/runtime/demo` continua funcionando sem credencial por meio de identidade demo explícita e controlada quando `ECOS_AUTH_DEMO_ENABLED=true`.

## Knowledge Graph

O Knowledge Graph real está em `backend/src/ecos/knowledge/` e representa significado organizacional estruturado: entidades, relacionamentos direcionais, versões, proveniência e referências seguras. Ele não armazena documentos brutos, binários, políticas integrais, recommendations integrais, reasoning integral ou cadeia privada de pensamento. Também não raciocina, não recomenda, não decide, não aprova, não executa ação e não altera Memory, LearningResult, Session ou eventos históricos.

Entidades e relacionamentos são imutáveis e versionados. Correções, arquivamentos, substituições e merges geram novas versões; histórico não é apagado e não há hard delete. As consultas suportam versão atual, versão específica, histórico e `as_of` timezone-aware. Identidade e idempotência usam fingerprints SHA-256 derivados de campos seguros (`organization_id`, tipo, nome normalizado, namespace, identificadores externos confiáveis e atributos `identity_*`), nunca `hash()` do Python. Entidades parecidas não são mescladas automaticamente: merge exige operação explícita e auditável. Relação lexical não vira identidade, e associação não vira causalidade.

Tipos canônicos incluem organização, unidade, departamento, time, pessoa, papel, projeto, objetivo, decisão, reunião, política, procedimento, risco, oportunidade, cliente, fornecedor, produto, serviço, referência documental, memória, sessão, especialista, recomendação, execução, observação, aprendizagem, métrica, sistema, recurso, artefato e evento externo. Relações direcionais incluem `owns`, `belongs_to`, `created_by`, `depends_on`, `relates_to`, `supports`, `contradicts`, `affects`, `generated`, `approved_by`, `executed_by`, `learned_from`, `references`, `replaces`, `extends`, `governed_by`, `resulted_in`, `observed_by`, `measured_by`, `associated_with`, `occurred_after`, `correlated_with`, `part_of`, `assigned_to`, `uses`, `produces`, `mitigates`, `exposes` e `requires`.

Travessia é determinística e limitada: vizinhos diretos, caminhos breadth-first, cadeia de dependência, cadeia de impacto e subgrafo respeitam `organization_id`, profundidade, número máximo de nós, confiança mínima e filtros de tipo/status. Ciclos são permitidos em relações como `relates_to`; `depends_on` e `replaces` são acíclicas e geram erro/violação de integridade quando formam ciclo.

A recuperação semântica deste sprint é estruturada e lexical, sem OpenAI, `AIProvider`, LLM, embeddings, pgvector, Neo4j, banco vetorial, machine learning, busca externa ou chamadas externas. O ranking combina similaridade lexical/estruturada `0.35`, proximidade no grafo `0.20`, relevância por relacionamento `0.10`, importância `0.10`, recência `0.10`, confiança `0.10` e relevância organizacional `0.05`. Os pesos somam 1 e o desempate é determinístico por score, importância e `entity_id`.

O `KnowledgeContextExpander` fornece candidatos, caminhos e referências para o Context Engine, respeitando limites de profundidade, entidades, relacionamentos, orçamento e confiança. O Context Engine continua responsável pela seleção final do Unified Context e funciona com grafo vazio, registrando lacuna segura em vez de inventar conhecimento. Memory e Learning alimentam o grafo por eventos validados e replay-safe: Memory rejeitada ou Learning rejeitada não entram como conhecimento ativo.

O repositório padrão é `InMemoryKnowledgeGraphRepository`, sem banco, arquivos, estado global ou chamadas externas. PostgreSQL é opcional com `ECOS_KNOWLEDGE_REPOSITORY=postgres`, reutiliza `ECOS_DATABASE_URL`, SQLAlchemy async e Alembic existentes, sem banco separado e sem fallback silencioso. A migration `20260711_05_create_knowledge_graph_tables.py` cria `knowledge_entity_versions` e `knowledge_relationship_versions`. A validação de integridade reporta relacionamentos quebrados, duplicidade ativa, conflitos de fingerprint, ciclos inválidos e problemas de versão sem modificar o grafo.

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

O resultado inclui `ComplianceReport`, `ExplainabilityReport`, violações seguras, autorização escopada por Organization, Session, Plan e ação, requisitos de aprovação, request de aprovação quando necessário e audit trail append-only. A infraestrutura de observabilidade projeta e persiste `AuditRecord` a partir dos eventos de governança sem armazenar política integral, recommendation integral, reasoning integral, stack trace pública ou credenciais. Explainability exige objetivo, evidência, resumo de raciocínio, assumptions, riscos, alternativas, confidence 0–1, lacunas e recomendação; o Engine valida presença, estrutura e rastreabilidade básica, não a qualidade intelectual do raciocínio.

Os níveis oficiais de aprovação são Level 1 a Level 5. Level 1 pode autorizar automaticamente continuidade cognitiva de baixo risco e baixo impacto, mas não autoriza execução externa. Execution sempre exige autorização válida e aprovação humana explícita quando solicitada. Requests de aprovação passam pelos estados `pending`, `partially_approved`, `granted`, `rejected`, `expired`, `revoked` e `cancelled`; uma pessoa não conta duas vezes, papéis e quorum são validados, rejeição bloqueia e revogação invalida autorização dependente. A autenticação real não foi implementada: o `IdentityPort` consome uma identidade previamente validada por uma porta injetada.

O Runtime continua delegando ao Orchestrator. O Orchestrator invoca Governance como estágio do plano, preserva o `GovernanceResult`, entra em `waiting_approval` quando houver aprovação pendente e não transforma pending em granted. `/runtime/demo` continua retornando `status="completed"`, `recommendation="Proceed using ECOS context, reasoning, debate and governance."` e `confidence=0.91`, sem simular aprovação humana ou executar ação externa.

## Execution Layer

A Execution Layer real está em `backend/src/ecos/execution/` e transforma uma ação aprovada em operação controlada. Ela não decide, não recomenda, não altera `CognitivePlan`, `DecisionPackage` ou `GovernanceResult`, não concede aprovação e não acessa LLM, `AIProvider`, Container, variáveis de ambiente, SQLAlchemy, PostgreSQL ou sistemas externos diretamente.

Toda comunicação operacional passa por `ExecutionConnector` registrado em `ConnectorRegistry` injetado. A seleção é determinística por `connector_id`, fallback explicitamente permitido, capability autorizada, prioridade e `connector_id`; conectores indisponíveis, incompatíveis ou fora da autorização são rejeitados. A configuração padrão registra apenas um connector em memória para dry-run, sem ERP, CRM, APIs reais, navegador, agentes ou MCP reais.

Os contratos tipados cobrem execuções `human`, `system`, `api`, `agent`, `browser` e `mcp`, `ExecutionPlan` com DAG validado, constraints, recursos, janela, timeout, retry, fallback autorizado, artifacts por referência, métricas, logs seguros, timeline append-only, falhas classificadas, idempotência em memória e rollback explícito. `dry_run` é o padrão; `live` exige autorização explícita e connector com suporte a live.

Human execution cria `HumanTask` em memória e retorna `paused` com `ExecutionResumeState`; não finge conclusão. Rollback nunca é inventado: roda em ordem reversa apenas para etapas concluídas com `RollbackAction` explícita e autorização de rollback. Eventos de Execution são persistidos e projetados em auditoria, métricas, logs e traces quando passam pelo `EventService`. Resultados, timeline local, artifacts, idempotência e estado de retomada continuam pertencendo à Execution Layer; a Observability Layer armazena apenas fatos seguros e referências, nunca parâmetros integrais, credenciais, conteúdo binário ou payload integral de Connector.

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

Relevância, confiança e completude são calculadas de forma determinística e testável. A relevância considera correspondência com objetivo, entidades, políticas/restrições, tipo/importância da memória, confiança e recência, sem embeddings, busca web ou chamadas externas. Quando o Container injeta o Knowledge Graph real, o Context Engine consome candidatos e `ContextGraph` seguros por porta, sem acessar repository concreto ou SQLAlchemy e sem transferir a decisão final de contexto para o grafo. Lacunas de contexto permanecem explícitas em `missing_context`; elas reduzem `confidence` e `completeness` em vez de serem ocultadas.

## Memory Engine

O Memory Engine preserva o contrato `MemoryRepository` e oferece persistência em PostgreSQL via SQLAlchemy 2 e asyncpg. O fake continua como padrão; defina `ECOS_MEMORY_REPOSITORY=postgres` para persistência permanente e para ativar o Context Engine real no Container. Memórias podem carregar `organization_id`; o Context Engine exige esse escopo para recuperar contexto sem vazamento entre organizações. Este estágio não implementa busca vetorial, embeddings ou LLM.

## Observation Engine

O Observation Engine em `backend/src/ecos/observation/` mede resultados organizacionais declarados, comparando expectativas explícitas com medições, evidências e feedback fornecidos por providers injetados. Ausência de dados não equivale a sucesso; `completed` da observação significa processamento concluído, não outcome organizacional bem-sucedido. Ele não infere causalidade, não gera recomendação, não altera execução, plano ou decisão, não acessa Container, variáveis de ambiente, PostgreSQL, SQLAlchemy, OpenAI, `AIProvider` ou sistemas externos.

Os providers padrão são determinísticos e em memória. A Observability Layer agora persiste eventos e projeções técnicas/cognitivas, mas não substitui o Observation Engine: ela não recalcula outcome score, quality, LearningCandidate ou memória, e não infere causalidade.

## Learning Engine

O Learning Engine em `backend/src/ecos/learning/` é a fronteira obrigatória para criação ou atualização permanente de memória organizacional. Ele transforma `ObservationResult` validado em candidatos estruturados, calibra confiança por proposta versionada e só entrega conhecimento validado ao Memory Engine. Uma ocorrência não equivale a padrão; padrões exigem recorrência no histórico injetado. Aprendizagem estratégica, crítica ou sem aceitação explícita suficiente exige revisão humana.

Learning não explica causa sem evidência declarada, não sobrescreve confiança histórica, não apaga memória, não reescreve fatos e não reduz governança. Memória é evolutiva e não destrutiva: atualizações preservam origem, evidência, versão e proveniência. Nenhum LLM, embeddings, banco novo ou chamada externa foi adicionado ao Learning Engine.

## Backend

O backend usa Python 3.12, FastAPI, pydantic-settings, pytest, Ruff e uv. A interface operacional usa React, TypeScript, Vite e CSS próprio. Para execução local, Docker, credenciais demo e validação E2E, consulte `docs/local-development.md`.

## Interface operacional

O Sprint 18A adiciona a primeira interface operacional real em `frontend/`. Ela consome exclusivamente `/api/v1`, não acessa banco de dados e não contém lógica cognitiva. As áreas implementadas são login, visão geral, sessões cognitivas, aprovações, execuções, Knowledge Graph, auditoria/observabilidade e administração organizacional.

Autenticação de navegador usa cookie HttpOnly (`ECOS_WEB_COOKIE_NAME`) e proteção CSRF (`ECOS_CSRF_COOKIE_NAME` + `ECOS_CSRF_HEADER_NAME`) para operações mutáveis. O suporte a Bearer token existente permanece para clientes programáticos. Produção recusa inicialização com demo habilitado, segredo fraco ou repositórios críticos fora do PostgreSQL.

Credenciais demo locais:

- `operator@demo.ecos.local` / `operator-demo-password`
- `approver@demo.ecos.local` / `approver-demo-password`
- `auditor@demo.ecos.local` / `auditor-demo-password`
- `admin@demo.ecos.local` / `admin-demo-password`
- `operator@tenant-b.ecos.local` / `tenant-b-demo-password`

Esses dados são criados apenas quando `ECOS_DEMO_SEED_ENABLED=true` fora de produção.

## API operacional versionada

Endpoints principais:

- `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/auth/me`
- `/api/v1/organization`, `/api/v1/overview`
- `/api/v1/sessions`, `/api/v1/sessions/{id}`, `/api/v1/sessions/{id}/start`
- `/api/v1/recommendations/{session_id}`
- `/api/v1/approvals`, `/api/v1/approvals/{id}/approve`, `/api/v1/approvals/{id}/reject`
- `/api/v1/executions`, `/api/v1/executions/{id}/start`
- `/api/v1/observations`, `/api/v1/learning`
- `/api/v1/knowledge/search`, `/api/v1/knowledge/entities/{entity_id}`
- `/api/v1/events`, `/api/v1/audit`, `/api/v1/metrics`, `/api/v1/health/components`
- `/api/v1/admin/members`, `/api/v1/admin/roles`, `/api/v1/admin/permissions`, `/api/v1/admin/settings`

`/runtime/demo` foi preservado.

## Sprint 18B — persistência operacional

O fluxo operacional agora possui contrato próprio em `ecos.operational.repository`.
A seleção é explícita por `ECOS_OPERATIONAL_REPOSITORY=memory|postgres`; produção
recusa inicialização sem PostgreSQL. O modo `memory` é somente para desenvolvimento
declarado e testes unitários, sem fallback silencioso quando PostgreSQL é selecionado.

A migration `20260712_01_create_operational_tables.py` adiciona:

- `operational_sessions`: agregado persistente versionado, com `organization_id`,
  `status`, `correlation_id`, `approval_id`, `execution_id`, timestamps e JSON seguro
  do estado operacional.
- `operational_timeline_entries`: histórico append-only planejado para timeline.
- `operational_approval_decisions`: decisões de aprovação/rejeição sem hard delete.
- `operational_execution_attempts`: tentativas de execução sem hard delete.
- `operational_idempotency_keys`: resultado do primeiro comando mutável escopado por
  organização, usuário, operação e `Idempotency-Key`.

As transições de sessão, recomendação, aprovação, rejeição e execução usam optimistic
locking por `version`. Uma aprovação decidida retorna 409 em repetição não idempotente;
execução sem aprovação permanece bloqueada; solicitante não aprova a própria solicitação.
Com `Idempotency-Key`, criação de sessão, início do fluxo, aprovação, rejeição e início
de execução retornam o mesmo resultado para payload idêntico e 409 para payload diferente.
A retenção documentada das chaves é 24 horas; limpeza operacional pode ser feita com
`scripts/cleanup-operational-retention.sh`.

Reconciliação administrativa está disponível em `POST /api/v1/admin/reconcile` para
administradores organizacionais. Ela localiza estados interrompidos, registra timeline,
não aprova automaticamente e não inicia execução. Estados `processing`/`executing` são
marcados para revisão/falha segura; `waiting_approval`/`approved` são preservados para
retomada humana.

Não foi criada transactional outbox adicional neste sprint. A arquitetura atual já
centraliza Events/Audit/Observability no `EventService`; o novo repositório operacional
persiste o estado antes de publicar eventos derivados. A lacuna conhecida é que, sem uma
outbox, uma falha entre commit operacional e publicação pode exigir reconciliação/admin
replay manual. A escolha evita complexidade de fila local enquanto os eventos continuam
append-only no Event Store configurado.

## Health, readiness e métricas

- `/health/live`: liveness sem dependência externa.
- `/health/ready`: readiness das dependências configuradas.
- `/health/version`: versão, serviço e ambiente.
- `/metrics`: métricas operacionais em texto compatível com coleta simples, sem dados pessoais nas labels.

## Docker e CI

A imagem final integra frontend compilado e API, roda com usuário não-root e não inclui toolchain Node. `docker-compose.yml` define PostgreSQL, serviço separado de migrations e aplicação. O workflow `.github/workflows/ci.yml` executa lint, format check, testes, build frontend, validação de migrations, `docker compose config` e build da imagem.

## Backup, restore e retenção

Scripts operacionais simples ficam em `scripts/`:

- `backup-postgres.sh`: executa `pg_dump --format=custom` em `ECOS_DATABASE_URL`,
  valida o dump com `pg_restore --list` e grava em `ECOS_BACKUP_DIR` ou `./backups`.
- `restore-postgres.sh`: restaura `ECOS_RESTORE_FILE` com `pg_restore --clean --if-exists`.
- `cleanup-operational-retention.sh`: remove chaves de idempotência expiradas.

Disaster recovery local: parar a aplicação, restaurar backup em banco limpo, aplicar
`uv run alembic upgrade head`, iniciar a aplicação e validar `/health/ready`,
`/health/version`, login e uma consulta operacional. Rollback de migration deve ser
testado em banco descartável com `uv run alembic downgrade -1`; dados auditáveis,
aprovações, execuções e aprendizados validados não devem ser limpos sem política explícita.

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

### Observability

```bash
cd backend
export ECOS_OBSERVABILITY_REPOSITORY=memory   # padrão
```

Para persistir eventos, auditoria e projeções em PostgreSQL:

```bash
cd backend
export ECOS_DATABASE_URL=postgresql://ecos:ecos@localhost:5432/ecos
export ECOS_OBSERVABILITY_REPOSITORY=postgres
uv run alembic upgrade head
```

A migration `20260711_04_create_observability_tables.py` cria `event_records`, `audit_records`, `metric_records`, `trace_records`, `trace_spans`, `structured_log_records`, `alert_records` e `health_snapshot_records`. O modo padrão da suíte não exige PostgreSQL e `/runtime/demo` permanece compatível: `status="completed"`, recommendation `"Proceed using ECOS context, reasoning, debate and governance."` e `confidence=0.91`.

### Executar lint e formatação

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
```
