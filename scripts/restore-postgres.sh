#!/usr/bin/env sh
set -eu

: "${ECOS_DATABASE_URL:?ECOS_DATABASE_URL is required}"
: "${ECOS_RESTORE_FILE:?ECOS_RESTORE_FILE is required}"

if [ ! -f "$ECOS_RESTORE_FILE" ]; then
  printf '%s\n' "restore file not found" >&2
  exit 2
fi

if [ -f "$ECOS_RESTORE_FILE.sha256" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c "$ECOS_RESTORE_FILE.sha256"
  else
    shasum -a 256 -c "$ECOS_RESTORE_FILE.sha256"
  fi
fi

pg_restore --list "$ECOS_RESTORE_FILE" >/dev/null

if [ "${ECOS_RESTORE_ASSUME_EMPTY:-false}" != "true" ]; then
  TABLE_COUNT="$(psql "$ECOS_DATABASE_URL" -Atc "select count(*) from information_schema.tables where table_schema='public';")"
  if [ "$TABLE_COUNT" != "0" ]; then
    printf '%s\n' "target database is not empty; set ECOS_RESTORE_ASSUME_EMPTY=true only after explicit approval" >&2
    exit 3
  fi
fi

if [ "${ECOS_RESTORE_CONFIRM:-}" != "RESTORE_ECOS" ]; then
  printf '%s\n' "set ECOS_RESTORE_CONFIRM=RESTORE_ECOS to confirm restore" >&2
  exit 4
fi

pg_restore "$ECOS_RESTORE_FILE" --dbname="$ECOS_DATABASE_URL" --no-owner
psql "$ECOS_DATABASE_URL" -v ON_ERROR_STOP=1 -c "select count(*) from alembic_version;" >/dev/null
