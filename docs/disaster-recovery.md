# Disaster Recovery

## Objetivos

- RPO inicial: até o último backup PostgreSQL validado.
- RTO inicial: tempo para provisionar banco vazio, restaurar dump custom e iniciar aplicação com readiness verde.

## Backup

```bash
ECOS_DATABASE_URL=postgresql://... \
ECOS_BACKUP_DIR=/var/backups/ecos \
scripts/backup-postgres.sh
```

O script usa `pg_dump --format=custom --no-owner`, valida com `pg_restore --list`, gera `.sha256` e `.meta` com URL redigida.

Retenção:

```bash
ECOS_BACKUP_RETENTION_DAYS=14 scripts/backup-postgres.sh
```

A rotina lista candidatos expirados, mas não apaga auditoria nem dumps automaticamente.

## Restore

Restore exige banco vazio por padrão e confirmação explícita:

```bash
ECOS_DATABASE_URL=postgresql://... \
ECOS_RESTORE_FILE=/var/backups/ecos/ecos-YYYYMMDDTHHMMSSZ.dump \
ECOS_RESTORE_CONFIRM=RESTORE_ECOS \
scripts/restore-postgres.sh
```

Para restore controlado em alvo não vazio, use `ECOS_RESTORE_ASSUME_EMPTY=true` somente após aprovação explícita e validação de ambiente.

## Validação Pós-Restore

1. `alembic current`.
2. `/health/ready`.
3. Login demo/local somente fora de produção.
4. Consulta de sessão operacional restaurada.
5. Consulta de eventos/auditoria por `correlation_id`.
6. Processamento explícito de outbox pendente, se houver.

## Rollback de Migration

Use rollback de migration apenas com janela de manutenção:

```bash
cd backend
uv run alembic downgrade -1
uv run alembic upgrade head
```

Backups devem ser capturados antes de qualquer downgrade. Eventos e auditoria são append-only e não devem ser removidos por rotina genérica.
