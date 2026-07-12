#!/usr/bin/env sh
set -eu

: "${ECOS_DATABASE_URL:?ECOS_DATABASE_URL is required}"
BACKUP_DIR="${ECOS_BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/ecos-$STAMP.dump"
META_FILE="$BACKUP_FILE.meta"
CHECKSUM_FILE="$BACKUP_FILE.sha256"

pg_dump "$ECOS_DATABASE_URL" --format=custom --no-owner --file="$BACKUP_FILE"
pg_restore --list "$BACKUP_FILE" >/dev/null
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$BACKUP_FILE" > "$CHECKSUM_FILE"
else
  shasum -a 256 "$BACKUP_FILE" > "$CHECKSUM_FILE"
fi
{
  printf 'created_at=%s\n' "$STAMP"
  printf 'format=pg_dump_custom\n'
  printf 'database_url_redacted=%s\n' "$(printf '%s' "$ECOS_DATABASE_URL" | sed -E 's#//([^:/@]+):([^@]+)@#//[REDACTED]:[REDACTED]@#')"
  printf 'checksum_file=%s\n' "$(basename "$CHECKSUM_FILE")"
} > "$META_FILE"

if [ "${ECOS_BACKUP_RETENTION_DAYS:-0}" -gt 0 ]; then
  find "$BACKUP_DIR" -type f -name 'ecos-*.dump' -mtime "+$ECOS_BACKUP_RETENTION_DAYS" -print
fi

printf '%s\n' "$BACKUP_FILE"
