# Codex Instructions for ECOS

These rules apply to the entire repository.

- Do not change the architecture without explicit authorization.
- Keep modules decoupled and avoid unnecessary cross-module dependencies.
- Write tests for every new or changed functionality.
- Do not implement LLM integrations directly without an abstraction layer.
- Use explicit typing in code and public interfaces.
- Update documentation whenever behavior changes.
- Never place secrets, credentials, tokens, or private keys in the repository.
