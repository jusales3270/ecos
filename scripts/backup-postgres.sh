#!/usr/bin/env sh
set -eu

: "${ECOS_DATABASE_URL:?ECOS_DATABASE_URL is required}"
BACKUP_DIR="${ECOS_BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
pg_dump "$ECOS_DATABASE_URL" --format=custom --no-owner --file="$BACKUP_DIR/ecos-$STAMP.dump"
pg_restore --list "$BACKUP_DIR/ecos-$STAMP.dump" >/dev/null
printf '%s\n' "$BACKUP_DIR/ecos-$STAMP.dump"
