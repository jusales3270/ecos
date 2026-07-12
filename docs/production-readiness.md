# Production Readiness

Versão RC: `0.1.0-rc.1`.

## Checklist

- `ECOS_ENVIRONMENT=production`.
- Repositórios críticos em PostgreSQL: security, operational, observability e sessions.
- `ECOS_AUTH_TOKEN_KEY_RING` configurado com segredos fortes e `ECOS_AUTH_ACTIVE_KEY_ID` apontando para a chave ativa.
- `ECOS_AUTH_DEMO_ENABLED=false` e `ECOS_DEMO_SEED_ENABLED=false`.
- `ECOS_ALLOWED_ORIGINS`, `ECOS_ALLOWED_HOSTS` e `ECOS_TRUSTED_PROXY_CIDRS` definidos explicitamente.
- Migrations aplicadas até `20260712_02`.
- `/health/live` retorna 200 sem banco.
- `/health/ready` retorna 200 somente com conectividade, schema e tabelas essenciais válidos.
- `/health/version` informa versão, ambiente, build metadata e schema revision.
- Backups validados e restore testado em banco vazio.

## Outbox

O fluxo operacional PostgreSQL grava estado e mensagens em `transactional_outbox` na mesma transação. O processamento local usa `SELECT ... FOR UPDATE SKIP LOCKED`, suporta múltiplas instâncias, retries com backoff limitado, recuperação de `processing` preso e entrega idempotente pelo `event_id` no Event Store.

O processamento automático no startup só roda quando `ECOS_OUTBOX_PROCESS_ON_STARTUP=true`. Operação manual: `POST /api/v1/admin/outbox/process`.

## Readiness

Readiness valida:

- transação curta `select 1`;
- tabela `alembic_version` e revision atual;
- tabelas essenciais de security, operational, observability e outbox;
- configuração de produção sem demo;
- segredo JWT adequado.

Readiness não executa queries pesadas e não expõe credenciais.

## Riscos Aceitos

- Sem scanner de imagem obrigatório local; CI gera SBOM e deixa scan depender de ferramenta disponível.
- Sem fila externa; outbox é PostgreSQL-only por restrição de não adicionar Redis/Kafka/Celery.
- Sem deploy automático, tag automática ou publicação automática.
- Docker Scout local em `ecos-app:latest` reportou CVEs de base Debian em `perl` com 1 crítica e 2 altas sem fixed version publicado no momento da validação. O risco fica aceito para o RC somente com imagem não-root, sem segredos copiados, SBOM gerado e acompanhamento por Dependabot/base image updates.
- O engine SQLAlchemy usa `NullPool` porque os adapters atuais são síncronos e criam event loops por chamada; pooling asyncpg real exige refatoração dos adapters para async end-to-end para evitar conexões presas a outro loop.
