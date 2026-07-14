# SARA Presence Layer

## Papel e limites

SARA é uma interface persistente do E.C.O.S., não um agente com autoridade própria. Ela registra entradas como objetivos ou interações de uma Cognitive Session e pode orientar navegação interna. Não aprova decisões, não contorna Planner, Orchestrator ou Governance e não inicia a Execution Layer.

A interface só afirma estados comprovados pela API. A saudação declara explicitamente seus limites e não presume observação em tempo real.

## Arquitetura

- `SaraPresenceLayer` controla modos, foco, voz, interação, atalhos e navegação.
- `SaraHologram` preserva a identidade âmbar e o sistema de partículas em canvas.
- `saraApi` usa cookies, CSRF e o endpoint versionado do E.C.O.S.
- `saraActions` valida uma whitelist antes de usar o router.
- `saraStorage` persiste apenas preferências isoladas por organização e usuário.
- `saraTypes` define os contratos públicos do frontend.

O shell monta a camada em `SaraPresenceMount`, acima do `Outlet`. Assim ela permanece montada durante navegação autorizada e não altera `/runtime/demo`.

## Modos e estados

Os modos são `closed` (somente invocador), `full` (overlay modal) e `mini` (widget arrastável). O mini é limitado à viewport e recalculado no resize. Clique sem arrastar expande; arrastar move o widget inteiro.

Estados visuais: `idle`, `listening`, `thinking`, `speaking`, `offline`, `error`, `waiting_approval` e `executing`. Os dois últimos só são usados quando retornados pelo estado real da sessão.

## Fluxo e API

`POST /api/v1/sara/interactions` requer autenticação e CSRF. A organização e o usuário vêm exclusivamente do principal autenticado.

```json
{
  "message": "texto, até 2000 caracteres",
  "history": [{ "role": "user", "content": "contexto limitado" }],
  "session_id": "UUID opcional",
  "route_context": "/rota-interna"
}
```

```json
{
  "interaction_id": "UUID",
  "session_id": "UUID",
  "response": "texto simples",
  "runtime": {
    "state": "waiting_approval",
    "lifecycle_status": "PAUSED",
    "stage": "GOVERNANCE",
    "active_engine": "governance",
    "progress": 0.8,
    "version": 1,
    "updated_at": "2026-07-13T12:00:00Z",
    "error_code": null
  },
  "ui_actions": [{ "type": "open_approvals", "session_id": null }],
  "incomplete_context": false,
  "unavailable": false
}
```

Sem `session_id`, o serviço cria a sessão operacional e uma `CognitiveSession` com o mesmo UUID e inicia o runtime autenticado até o gate real de governança. Com ID, exige a organização autenticada e não reinicia um runtime que já possua checkpoint. A SARA não aprova nem inicia a Execution Layer; histórico continua limitado à interface e não concede identidade ou autoridade.

Antes de chamar Planner ou Orchestrator, o runtime adquire atomicamente um claim persistente por `organization_id + session_id`. Em PostgreSQL, a aquisição usa inserção com conflito controlado e bloqueio da linha; workers perdedores apenas observam o estado confirmado. Claims que falham antes do planejamento ficam marcados como `failed` e podem ser readquiridos com incremento de tentativa. A criação da `CognitiveSession` também é atômica e só é idempotente quando sessão, organização e objetivo coincidem.

`GET /api/v1/sara/sessions/{session_id}/state` retorna apenas a projeção segura confirmada por `SessionService` e pelo checkpoint. A resposta usa `ETag`, aceita `If-None-Match` com retorno `304` e fornece `Retry-After` para estados não terminais. Histórico, prompts, artefatos, resultados internos e mensagens de providers não são expostos.

O frontend conserva o último runtime confirmado, reutiliza o `ETag` em `If-None-Match` e agenda a próxima consulta exclusivamente pelo `Retry-After`. Respostas `304` não alteram o estado visual. O polling é cancelado ao desmontar, trocar de sessão ou receber `completed`/`error`; respostas atrasadas de sessões anteriores são descartadas.

## Ações permitidas

A API da SARA emite somente abertura de sessão, aprovações ou execuções, além de fechamento e minimização de painéis. O frontend rejeita URL externa, JavaScript, seletor DOM, shell e qualquer tipo desconhecido. Aprovação, rejeição, início de execução e alteração de dados nunca são ações da SARA.

## Persistência e segurança

`localStorage` usa `ecos:sara:v1:{organization_id}:{user_id}` e guarda somente modo, posição mini, voz e permissão de expansão. Mensagens, respostas, tokens e credenciais não são persistidos. Histórico é limitado a 12 itens, texto é renderizado como texto React e respostas são validadas antes do uso.

Erros 401 e 429 têm mensagens específicas. O isolamento organizacional é aplicado no serviço e repositório existentes.

## Acessibilidade e interação

Botões têm nomes acessíveis, o input possui label, o status usa `aria-live`, o overlay controla foco e Escape minimiza. `Alt+S` invoca ou fecha a presença e não é capturado enquanto o usuário digita. Pointer Events atendem mouse e touch; foco visível e contraste âmbar são mantidos.

## Desempenho

O sistema base contém 2.200 partículas e é criado uma vez por montagem. O modo full usa a qualidade completa, mini reduz para 650, reduced motion reduz para 260, DPR é limitado a 1.5 e aba oculta reduz atualizações. RAF e listeners são cancelados no cleanup.

## Voz e TTS

Web Speech API é progressiva e respeita a preferência de voz. Reconhecimento indisponível mantém o input textual. Síntese e reconhecimento são cancelados no cleanup e a saudação não fala automaticamente durante navegação.

Defina `VITE_SARA_TTS_URL` com a URL de um endpoint autenticado do E.C.O.S. que aceite `{ "text": "..." }` e devolva áudio. O navegador nunca chama um provider diretamente. Falhas usam Web Speech como fallback; áudio anterior é cancelado e blob URLs são revogadas. Deixe a variável vazia para usar somente Web Speech.

## Motor visual volumétrico

O Sprint 19C restaura o motor Canvas 2D oficial em `saraHologramEngine.ts`: sete bandas orbitais em ângulo áureo, 2.200 partículas no modo expandido, projeção e oclusão 3D, 42 arcos, três anéis giroscópicos e 13 nós neurais. O modo mini e `prefers-reduced-motion` reduzem o orçamento de renderização sem criar um segundo motor. Estados adicionais do E.C.O.S. são somente mapeamentos visuais; não representam aprovação ou execução por parte da SARA.

O pulso de fala é produzido por eventos `boundary` do Web Speech, pela amplitude do áudio TTS quando o navegador permite conectar um analisador e por temporização de palavras como fallback. Essa instrumentação não inicia nem duplica a reprodução de áudio.

## Evolução futura

Browser Execution e automação desktop poderão consumir novos tipos de ação somente depois de contratos autenticados, confirmação humana, políticas e auditoria próprias. O contrato atual não controla navegador externo, desktop ou aplicativos do sistema.
