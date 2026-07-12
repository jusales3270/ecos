# Cognitive OS Interface

Sprint 19A refactors the ECOS frontend into a cognitive operating system interface for enterprise operations. The UI remains a client for existing ECOS APIs; it does not add authority, bypass governance, or invent operational data.

## Interface Architecture

The authenticated application is mounted through `CognitiveOsShell`. It owns the persistent operating frame:

- `SystemTopBar`: active organization, environment, version, system health, current user, global ECOS state, and Command Palette entry.
- `CognitiveRail`: primary navigation for cognitive areas, filtered by permissions already present in the authenticated principal.
- `CognitiveWorkspace`: route content rendered by React Router through the central surface.
- `ContextInspector`: lateral context panels inside pages that have real context to inspect, especially cognitive sessions and overview.
- `EventConsole`: persistent bottom console populated from existing event API data.
- `CommandPalette`: keyboard-accessible navigation palette. It navigates between areas only; it does not execute privileged actions.
- `SaraPresenceMount`: an empty persistent mount point above route content for the future SARA presence layer.

The shell reads only existing contracts: `/api/v1/auth/me`, `/api/v1/overview`, `/api/v1/events`, `/health/version`, and the route-specific APIs already used by the previous frontend.

## Main Areas

The navigation rail exposes the cognitive operating areas requested for the sprint:

- Visão Cognitiva
- Sessões
- Memória
- Knowledge Graph
- Governança
- Aprovações
- Execuções
- Observabilidade
- Aprendizado
- Administração, only when the authenticated principal has `organization:admin`

Areas without a dedicated frontend API endpoint, such as the standalone memory area, show an explicit empty or unavailable state instead of fabricated records.

## Cognitive Cycle

Session detail pages render the cognitive pipeline:

Contexto -> Raciocínio -> Debate -> Simulação -> Recomendação -> Aprovação -> Execução -> Observação -> Aprendizado

The highlighted stage is derived from the session status returned by the API. Completed stages are derived from the session `stages` payload and support the existing English stage names returned by backend services.

The workspace shows available session artifacts from the real recommendation payload:

- reasoning
- debate
- simulation
- summary
- decision
- risks
- evidence
- plan

Missing artifacts are labeled as unavailable in the current stage.

## Frontend Authority Limits

The frontend is not an authority boundary. It uses principal permissions to hide or disable sensitive controls, but the backend remains responsible for enforcement.

Visible limits are part of the UI:

- recommendation is not a decision;
- execution requires explicit human approval;
- approval controls require `decisions:approve`;
- execution controls require `execution:execute`;
- session creation and cognition start require `sessions:write`;
- organization administration requires `organization:admin`;
- cross-organization isolation remains server-side and unchanged.

The interface does not call LLMs directly and does not introduce autonomous execution flows.

## SARA Integration Point

`SaraPresenceMount` is intentionally empty and persistent inside `CognitiveOsShell`, above routed pages. It creates a stable architectural mounting point for a future `SaraPresenceLayer` without implementing a widget, avatar, hologram, mock behavior, or synthetic SARA state in Sprint 19A.
