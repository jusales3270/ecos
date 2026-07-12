#!/usr/bin/env sh
set -eu

: "${ECOS_DATABASE_URL:?ECOS_DATABASE_URL is required}"
psql "$ECOS_DATABASE_URL" \
  -c "delete from operational_idempotency_keys where expires_at <= now();"
