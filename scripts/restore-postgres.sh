#!/usr/bin/env sh
set -eu

: "${ECOS_DATABASE_URL:?ECOS_DATABASE_URL is required}"
: "${ECOS_RESTORE_FILE:?ECOS_RESTORE_FILE is required}"
pg_restore "$ECOS_RESTORE_FILE" --dbname="$ECOS_DATABASE_URL" --clean --if-exists --no-owner
