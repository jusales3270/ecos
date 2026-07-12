# Security Operations

## Authentication

Autenticação local usa senha Argon2id e JWT HS256 via PyJWT. Produção deve configurar:

```bash
ECOS_AUTH_TOKEN_KEY_RING=2026-07:key-forte-atual,2026-06:key-anterior
ECOS_AUTH_ACTIVE_KEY_ID=2026-07
ECOS_AUTH_ISSUER=ecos.production
ECOS_AUTH_AUDIENCE=ecos.api
```

O header JWT inclui `kid`. Chave desconhecida é rejeitada. Chaves antigas continuam aceitas enquanto permanecerem no key ring configurado.

## Revocation

Logout individual revoga o `token_id` persistido em `security_auth_sessions`. Tokens revogados ou expirados retornam 401. Revogação global/por usuário/por organização deve ser operada por rotina administrativa que marque sessões persistidas como revogadas; não há IdP externo.

## Login Throttling

Login usa contador persistente por identidade normalizada e origem. A resposta de falha é genérica e não confirma se o usuário existe. Configurações:

- `ECOS_LOGIN_THROTTLE_WINDOW_SECONDS`
- `ECOS_LOGIN_THROTTLE_LIMIT`
- `ECOS_LOGIN_THROTTLE_BLOCK_SECONDS`

## Rate Limiting

Rate limiting cobre login, `/api/v1`, admin, audit, knowledge e API geral. Health live/ready/version não é bloqueado. A chave considera rota, método, usuário/organização quando disponíveis e IP confiável.

Headers:

- `Retry-After` em 429;
- `X-RateLimit-Limit`;
- `X-RateLimit-Remaining`.

## API Hardening

- CORS exige allowlist.
- Trusted Hosts exige allowlist.
- Proxy headers só são confiáveis quando o IP direto está em `ECOS_TRUSTED_PROXY_CIDRS`.
- Payloads acima de 1 MB são rejeitados.
- CSP, frame denial, nosniff, Referrer-Policy, Permissions-Policy e cache no-store são aplicados.
- HSTS só é enviado em produção.
- OpenAPI/docs podem ser desabilitados por configuração.

## Secret Scanning

CI executa grep básico para chaves privadas e tokens comuns. Arquivos `.env` reais não devem ser versionados.
