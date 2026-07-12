# Changelog

## 0.1.0-rc.1 - 2026-07-12

Release candidate técnico do ECOS.

### Added

- Transactional outbox PostgreSQL para eventos operacionais, com retries, backoff, inspeção administrativa e processamento explícito.
- Throttling persistente de login e rate limiting determinístico com backend PostgreSQL ou memória local/teste.
- JWT key ring com `kid`, issuer/audience obrigatórios e rejeição de chave desconhecida.
- Readiness com schema revision, tabelas essenciais e componentes resumidos.
- Versão central em `VERSION`, endpoint `/health/version` e exibição no frontend.
- Scripts de backup/restore com formato custom, checksum, metadados e confirmação explícita.
- CI com auditorias de dependências, SBOM, secret scan, Docker checks e backup smoke.

### Changed

- PostgreSQL usa pool com `pre_ping`, timeout de conexão, statement timeout, lock timeout e reciclagem configurável.
- Persistência operacional PostgreSQL passa a materializar timeline, decisões e tentativas nas tabelas normalizadas.
- API adiciona CORS allowlist, Trusted Hosts, CSP, Permissions-Policy, HSTS em produção e rate-limit headers.

### Known Limitations

- O dashboard não foi redesenhado.
- Motores cognitivos não foram reescritos.
- A outbox transacional é aplicada ao repositório operacional PostgreSQL; modo memória publica eventos diretamente para preservar testes locais.
- Não há Redis, Kafka, Celery, Kubernetes, OAuth ou IdP externo.
- Scans de imagem dependem das ferramentas disponíveis no ambiente de CI/local.
