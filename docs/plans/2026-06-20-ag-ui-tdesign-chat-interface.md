---
title: "AG-UI + TDesign Chat Web Interface"
date: 2026-06-20
status: draft
kind: design
---
# AG-UI + TDesign Chat Web Interface

## 1. Goal

Add a web-based agentic chat interface to the Deverino harness, letting users interact with
the agent through a browser with the same capabilities the TUI provides: streaming text,
tool call visualization, session management, and real-time observability.  The interface
reuses the existing Vue 3 dashboard as an inspector panel alongside the new chat view.

## 2. Context

The harness currently has two user-facing surfaces:

| Surface | Tech | Capabilities |
|---------|------|-------------|
| TUI (`harness_poc/tui.py`) | Textual (terminal) | Full interactive agent chat, streaming, tool cards, Vim keys, session mgmt |
| Dashboard (`dashboard-ui/`) | Vue 3 + FastAPI | Read-only observability: overview, sessions, context maps, tokens, sub-agents, skills, event firehose |

There is **no web-based chat interface**.  The dashboard API (`harness_poc/api/routes.py`)
serves only read-only observability endpoints — no turn execution, no streaming agent
responses, no session creation from the web.

### Constraints

- **Keep the existing dashboard.**  The Vue 3 SPA, Pinia stores, and FastAPI routes are
  production code.  The chat interface must compose with them, not replace them.
- **Reuse the PydanticAI runtime.**  `PydanticAgentRuntime` (in `pydantic_runtime.py`)
  already handles streaming text + tool calls.  The web endpoint must delegate to the same
  runtime, not fork it.
- **Match the dark theme.**  The dashboard uses a GitHub-dark-inspired palette (`#0d1117`
  background, `#58a6ff` accent, etc.) defined in both `dashboard_theme.py` and
  `dashboard-ui/src/style.css`.  The chat UI must follow the same design tokens.

### Why AG-UI and TDesign Chat

The project already uses **PydanticAI** (`pydantic-ai>=1.97.0`) as its agent runtime.
PydanticAI has first-party **AG-UI protocol** integration via `pydantic_ai.ui.ag_ui` —
`AGUIAdapter.dispatch_request()` exposes any PydanticAI agent as an AG-UI-compatible
SSE endpoint, handling request parsing, agent execution, event encoding, and streaming
automatically.

On the frontend, **TDesign Chat** (`@tdesign-vue-next/chat`) is the only Vue 3 component
library with native AG-UI protocol support.  It provides:

- Built-in message content types: `markdown`, `thinking`, `toolcall`, `search`, `suggestion`
- `useAgentToolcall` hook for custom tool call card rendering
- `useAgentState` hook for state synchronization (context map, token budget)
- SSE streaming with auto-reconnect
- Full slot-based customization (avatar, content, action bar, datetime)

Together they reduce what would be a ~1-week custom build to a 2–3 day integration.

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                      │
│  ┌──────────┬─────────────────────┬────────────────────────┐  │
│  │ Sessions │  TDesign Chat       │  Dashboard (existing)  │  │
│  │ (pinia)  │  <t-chatbot>        │  Inspector panel       │  │
│  │          │  protocol="agui"    │  Overview / ContextMap  │  │
│  │          │  SSE streaming      │  Tokens / SubAgents     │  │
│  └──────────┴─────────┬───────────┴────────────────────────┘  │
│                       │ AG-UI events (SSE)                    │
│                       │ GET /api/overview, /api/sessions, ... │
└───────────────────────┼───────────────────────────────────────┘
                        │
┌───────────────────────┼───────────────────────────────────────┐
│  FastAPI (harness_poc/api/)                                    │
│  ┌────────────────────┴───────────────────────────────────┐   │
│  │  POST /api/chat  →  AG-UI event stream                 │   │
│  │    PydanticAI agent.run() → AG-UI events                │   │
│  │    Tool calls → ToolCallStart/Args/End/Result           │   │
│  │    Text → TextMessageStart/Content/End                  │   │
│  │    State → StateSnapshot/Delta                          │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │  Existing dashboard endpoints (unchanged)               │   │
│  │  GET /api/overview, /api/sessions, /api/events, ...     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  PydanticAgentRuntime (pydantic_runtime.py)               │   │
│  │    AgentDeps: session_id, database, skill_runner,         │   │
│  │               tool_runner, stream_text, on_tool_event     │   │
│  │    stream_text(prompt, message_history, on_text,          │   │
│  │                on_tool_event) → AgentRunResult            │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **AG-UI as the wire protocol.**  Instead of inventing custom SSE event types
   (`text_delta`, `tool_call`, `tool_result`, …), we emit AG-UI standard events.
   TDesign Chat understands them natively; other AG-UI-compatible frontends
   (assistant-ui, CopilotKit) could also consume them without backend changes.

2. **Adapter, not fork.**  We pass the raw PydanticAI `Agent` (from
   `PydanticAgentRuntime.agent`) to `AGUIAdapter.dispatch_request()`, which handles
   request parsing, agent execution, event encoding, and streaming automatically.
   The harness's custom `AgentDeps` (database, skill_runner, tool_runner) are passed
   through — `AGUIAdapter` uses the same deps the TUI and REPL use.  No manual event
   construction or thread-pool bridging needed.

3. **TDesign Chat in the existing SPA.**  TDesign Chat is a Vue 3 component library.
   It installs alongside the existing Vue, Pinia, and vue-router setup in `dashboard-ui/`.
   No new build tooling, no React interop, no iframe.

4. **Multi-pane layout.**  The current `App.vue` uses a single sidebar + `<router-view>`.
   We refactor to a resizable 3-pane layout: session list (left), chat (center),
   inspector dashboard panels (right).  The existing views become the inspector content.

## 4. AG-UI Event Mapping

The AG-UI protocol defines 25+ event types.  We implement the subset relevant to
the harness's agent loop:

| AG-UI Event | Emitted When | From Runtime Callback |
|---|---|---|
| `RunStartedEvent` | Turn begins | `stream_text()` call starts |
| `RunFinishedEvent` | Turn ends (success, error, or cancel) | `stream_text()` returns |
| `TextMessageStartEvent` | Agent starts a new message | First text chunk after model turn starts |
| `TextMessageContentEvent` | Streaming text delta | `on_text(chunk)` callback |
| `TextMessageEndEvent` | Agent finishes a message | End of text stream for this model turn |
| `ToolCallStartEvent` | Agent invokes a tool | `on_tool_event(tool_name, args)` — call start |
| `ToolCallArgsEvent` | Tool arguments (streamed, but ours are complete) | Immediate after ToolCallStart |
| `ToolCallEndEvent` | Tool call arguments complete | Immediate after ToolCallArgs |
| `ToolCallResultEvent` | Tool execution result | Tool returns result |
| `StateSnapshotEvent` | On connect: current token budget, session status | Built from `AgentDeps` + database |
| `StateDeltaEvent` | Token budget change after a turn | From `AgentRunResult.usage` |
| `RunErrorEvent` | Agent or tool exception | Exception in `stream_text()` or tool execution |
| `CustomEvent` | Frontend-specific signals (e.g., "context map updated") | Post-turn hooks |

### Why Not Agent-to-Agent Loop Events

PydanticAI's agent loop (model turn → tool call → model turn → …) is internal.
We don't emit AG-UI events for every model turn boundary — we emit one `RunStarted`
→ N × (TextMessage + ToolCall pairs) → `RunFinished` per user turn.  This keeps
the frontend simple: one user message = one streaming response block with interleaved
tool cards.

## 5. Backend Design

### 5.1 Dependencies

The `ag-ui-protocol` package (v0.1.18) is already a transitive dependency of
`pydantic-ai`.  Make it explicit in `pyproject.toml`:

```toml
[project.optional-dependencies]
agui = ["ag-ui-protocol>=0.1.18"]
```

The `pydantic-ai` package provides `pydantic_ai.ui.ag_ui.AGUIAdapter` — no
separate install needed for the adapter.

### 5.2 New Module: `harness_poc/api/chat.py`

The `AGUIAdapter.dispatch_request()` classmethod handles the entire request
lifecycle — request parsing, agent execution, event encoding, and SSE streaming.
The chat endpoint reduces to:

```python
"""AG-UI chat endpoint — bridges PydanticAgentRuntime to AG-UI SSE events."""

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic_ai.ui.ag_ui import AGUIAdapter

from harness_poc.core.storage.db_engine import create_db_engine

router = APIRouter()


@router.post("/api/chat")
async def chat_endpoint(request: Request) -> Response:
    """AG-UI chat endpoint.  AGUIAdapter handles everything."""
    session_id = _extract_session_id(request)
    runtime = _get_or_build_runtime(session_id, request.app.state)
    message_history = request.app.state.database.load_session_messages(session_id)

    return await AGUIAdapter.dispatch_request(
        request,                             # Starlette/FastAPI Request
        agent=runtime.agent,                 # The raw PydanticAI Agent
        deps=runtime.deps,                   # AgentDeps with database, tools, etc.
        message_history=message_history,     # Persisted model messages
        conversation_id=session_id,          # Maps to AG-UI threadId
    )
```

**Key points:**

- `AGUIAdapter.dispatch_request()` returns a Starlette `Response` with the correct
  `Content-Type` (`text/event-stream` or `application/vnd.ag-ui.event+proto`).
- The `AgentDeps` passed to `AGUIAdapter` are the same ones used by the TUI and
  REPL — no new deps class needed.  The `stream_text` and `on_tool_event` callbacks
  on `AgentDeps` are unused by `AGUIAdapter` (it handles streaming internally) and
  can be left as `None`.
- Message history is loaded from `DbSessionMessage` via
  `BlackboardDatabase.load_session_messages(session_id)`.  After the turn completes,
  the caller persists new messages via `append_session_messages()`.
- Session-level state (e.g., `CancellationToken`) is managed on `app.state`.

### 5.3 Post-Turn Message Persistence

`AGUIAdapter` does not persist messages — it only runs the agent and streams the
result.  After the SSE stream completes, the caller must persist the new messages.
We add a `BackgroundTask` or middleware for this:

```python
# In the endpoint, after AGUIAdapter returns:
# Option A: persist synchronously before returning (adds latency to first byte)
# Option B: persist via FastAPI BackgroundTasks after streaming
# For v1: persist via a post-turn hook that reads the latest messages from the
# agent's conversation history and appends them to DbSessionMessage.
```

The `chat_text()` function in `pydantic_runtime.py` (line 709) shows the pattern
for extracting messages post-turn.  For streaming turns, `AGUIAdapter` exposes the
result's `.new_messages()` via its internal agent run — we can subclass or wrap
the adapter for this.

**Alternative for v1 (simpler):** Let `AGUIAdapter` run the agent, then immediately
after the stream ends, call `runtime.agent.last_run_messages` (or equivalent) to
capture and persist the new messages.  Exact persistence API TBD during
implementation — depends on `AGUIAdapter`'s post-run surface.

### 5.4 Session Management Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/sessions` | List sessions (already exists — reuse) |
| POST | `/api/sessions` | Create new session, return `session_id` |
| DELETE | `/api/sessions/{id}` | Archive session |
| GET | `/api/sessions/{id}/history` | Return message history for resume |

Session metadata is already in the `sessions` PostgreSQL table.
`BlackboardDatabase.start_session(objective)` creates sessions;
`list_recent_sessions(limit)` lists them; `load_session_messages(session_id)`
returns message history via `DbSessionMessage`.

**Gap:** `BlackboardDatabase` has no `delete_session()` method.  One must be
added (soft-delete by setting `status = 'archived'`).

### 5.5 Cancel Endpoint

```
POST /api/chat/{session_id}/cancel
```

Sets a `CancellationToken` on the session's active run.  The runtime's tool
executor (`_execute_with_token` in `tool_runner.py`) already polls for
cancellation — we expose the token via `app.state.active_tokens[session_id]`.

**Limitation:** Cancellation only affects tool execution (skill/tool functions).
The LLM API call itself (HTTP request to OpenAI/Anthropic) and the agent loop
(model → tool → model) are not directly cancellable in v1.  The cancel token
is checked between tool rounds; if the agent is mid-LLM-call, cancellation takes
effect on the next tool invocation.

### 5.6 Wiring at Startup (`harness_poc/api/__init__.py`)

`create_app()` currently stores `engine` on `app.state`.  We add:

```python
app.state.database_url = database_url
app.state.active_tokens: dict[str, CancellationToken] = {}
```

`AGUIAdapter` needs a raw PydanticAI `Agent` + `AgentDeps` per turn.
These are built on-demand in the chat endpoint from `app.state.database_url`
(via `build_runtime_layer()` from `app_factory.py`), not stored globally.

`create_app_from_config()` already preloads the compiler model on
`app.state.compiler_model` — we keep that pattern.

## 6. Frontend Design

### 6.1 New Dependencies

Add to `dashboard-ui/package.json`:

```json
{
  "dependencies": {
    "@tdesign-vue-next/chat": "^0.5.2",
    "splitpanes": "^4.1.2"
  }
}
```

- `@tdesign-vue-next/chat` — TDesign Chat component library (Vue 3).  v0.5.2
  pulls in `tdesign-vue-next` (full component library), `tdesign-icons-vue-next`,
  `marked`, `highlight.js`, and `clipboard` as transitive dependencies.
- `splitpanes` — Resizable split panes (Vue 3 native, no jQuery).  v4.x API uses
  `<Splitpanes>` + `<Pane>` components with `size` props.

### 6.2 New Files

| File | Purpose |
|------|---------|
| `dashboard-ui/src/views/ChatView.vue` | Main chat view — wraps `<t-chatbot>`, handles SSE, manages session |
| `dashboard-ui/src/components/chat/ChatSidebar.vue` | Session list (left pane): create, resume, delete sessions |
| `dashboard-ui/src/components/chat/ToolCallCard.vue` | Custom tool call renderer registered via `useAgentToolcall` |
| `dashboard-ui/src/components/chat/ContextBudgetBar.vue` | Token usage bar synced via `useAgentState` |
| `dashboard-ui/src/stores/chat.ts` | Pinia store: active session, message buffer, tool call queue |
| `dashboard-ui/src/api/chat-sse.ts` | SSE client for `/api/chat` — connects to AG-UI stream |

### 6.3 Modified Files

| File | Change |
|------|--------|
| `App.vue` | Replace single `<router-view>` with 3-pane split layout |
| `router.ts` | Add `/chat` and `/chat/:sessionId` routes |
| `Sidebar.vue` | Add "Chat" nav link |
| `style.css` | Add TDesign theme variable overrides to match the dark palette |

### 6.4 Multi-Pane Layout (`App.vue`)

```
┌──────────┬─────────────────────────┬──────────────────────────┐
│ Sidebar  │  Chat View              │  Inspector               │
│ (56)     │                         │                          │
│          │  ┌───────────────────┐  │  ┌────────────────────┐  │
│ Overview │  │ User: Hello       │  │  │ Token Budget       │  │
│ Chat     │  │ Agent: streaming… │  │  │ ████████░░ 8.2K    │  │
│ Context  │  │ [tool: file_read] │  │  └────────────────────┘  │
│ Sessions │  │  ↳ result: …      │  │  ┌────────────────────┐  │
│ Sub-Ag.  │  │ Agent: I found…   │  │  │ Context Map        │  │
│ Tokens   │  └───────────────────┘  │  │ (mini view)        │  │
│ Skills   │  ┌───────────────────┐  │  └────────────────────┘  │
│          │  │ Type a message…   │  │  ┌────────────────────┐  │
│          │  └───────────────────┘  │  │ Active Sub-Agents  │  │
│          │                         │  │ (tree view)        │  │
│          │                         │  └────────────────────┘  │
└──────────┴─────────────────────────┴──────────────────────────┘
```

The **Inspector** pane (right) reuses existing dashboard components:

- `TokenBudgetBar` — mini version of the Tokens view, keyed to active session
- `ContextMapMini` — compact ContextMapTable filtered to active session's corpus
- `SubAgentTree` — small tree view from the SubAgents page
- `EventFirehose` — compact version, scoped to active session

These are already built as Pinia-driven components — they just need a `sessionId` prop
to scope their data fetches.

### 6.5 ChatView Component

```vue
<template>
  <div class="flex flex-col h-full">
    <!-- Session selector bar (top) -->
    <ChatSessionBar
      :session="activeSession"
      @new="createSession"
      @delete="deleteSession"
    />

    <!-- TDesign Chat component (fills remaining space) -->
    <t-chatbot
      ref="chatbotRef"
      :chat-service-config="chatConfig"
      :messages="messages"
      class="flex-1"
    />

    <!-- Context budget bar (bottom, synced via StateDelta) -->
    <ContextBudgetBar :session-id="activeSession?.id" />
  </div>
</template>

<script setup lang="ts">
import { useAgentToolcall, useAgentState } from '@tdesign-vue-next/chat'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()

const chatConfig = {
  endpoint: '/api/chat',
  protocol: 'agui',           // native AG-UI support
  stream: true,
  // Pass session metadata in the request body
  onRequest: (body: Record<string, unknown>) => ({
    ...body,
    sessionId: chatStore.activeSessionId,
    threadId: chatStore.activeSessionId,
  }),
}

// Register custom tool call renderers for harness-specific tools
useAgentToolcall('file_read', FileReadCard)
useAgentToolcall('file_write', FileWriteCard)
useAgentToolcall('container_exec', ContainerExecCard)
useAgentToolcall('web_search', WebSearchCard)
useAgentToolcall('semble_search', SembleSearchCard)
useAgentToolcall('delegate_task', DelegateTaskCard)

// Sync agent state (token budget) to the context bar
const { state } = useAgentState()
</script>
```

### 6.6 Custom Tool Call Cards

Each harness tool gets a domain-specific card component:

```
┌─────────────────────────────────────────────┐
│ 🔧 file_read  ·  src/auth.py:42-67          │
│ ┌─────────────────────────────────────────┐ │
│ │ def authenticate(user, password):       │ │
│ │     token = jwt.encode(...)             │ │
│ │     return token                         │ │
│ └─────────────────────────────────────────┘ │
│ ✓ 3.2KB · 12 lines                          │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 🐳 container_exec  ·  pytest --tb=short     │
│ ┌─────────────────────────────────────────┐ │
│ │ tests/test_auth.py::test_login PASSED   │ │
│ │ tests/test_auth.py::test_token FAILED   │ │
│ └─────────────────────────────────────────┘ │
│ ✓ exit code 1 · 1.4s                        │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ 👥 delegate_task  ·  code_reviewer          │
│ Objective: Review auth.py for security...   │
│ Status: completed · 12.3s                   │
│ ✓ No vulnerabilities found                  │
└─────────────────────────────────────────────┘
```

Each card registers via `useAgentToolcall(toolName, Component)`.  TDesign Chat
automatically renders them when the corresponding `ToolCallStart` event arrives.

### 6.7 Theme Integration

TDesign uses CSS variables for theming.  We override their defaults with the
harness's dark palette:

```css
/* Added to style.css */
:root {
  --td-brand-color: var(--accent-blue);
  --td-bg-color-container: var(--card-bg);
  --td-bg-color-page: var(--bg);
  --td-text-color-primary: var(--text);
  --td-text-color-secondary: var(--text-muted);
  --td-border-level-1-color: var(--card-border);
  --td-success-color: var(--accent-green);
  --td-error-color: var(--accent-red);
  --td-warning-color: var(--accent-yellow);
}
```

### 6.8 Change: vite.config.ts

TDesign Chat components need to be resolved.  If TDesign publishes ESM, no
config change needed.  If it uses a `tdesign-vue-next` base package, add
an alias or ensure the package is in `optimizeDeps`.

### 6.9 Chat Store (`stores/chat.ts`)

```typescript
export const useChatStore = defineStore('chat', () => {
  const activeSessionId = ref<string | null>(null)
  const sessions = ref<SessionSummary[]>([])
  const tokenBudget = ref<TokenBudget | null>(null)

  async function createSession(name?: string): Promise<string> { /* POST /api/sessions */ }
  async function loadSessions(): Promise<void> { /* GET /api/sessions */ }
  async function deleteSession(id: string): Promise<void> { /* DELETE /api/sessions/{id} */ }
  function setTokenBudget(budget: TokenBudget) { /* from StateDelta events */ }

  return { activeSessionId, sessions, tokenBudget, createSession, loadSessions, deleteSession, setTokenBudget }
})
```

## 7. Implementation Phases

### Phase 1 — Backend: AG-UI Chat Endpoint  ✅

- `ag-ui-protocol>=0.1.18` is already a transitive dep of `pydantic-ai`
- Created `harness_poc/api/chat.py` with `POST /api/chat` using `AGUIAdapter.dispatch_request()`
- Session endpoints: `GET/POST/DELETE /api/sessions/chat`, `GET /api/sessions/chat/{id}/history`
- Added `delete_session()` to `BlackboardDatabase` (soft-delete via `status='archived'`)
- Runtime caching on `app.state._chat_runtimes` (cold start ~30s, subsequent calls fast)
- Config fallback: `getattr(app.state, "config", None) or HarnessConfig.load()`
- Cancel endpoint: `POST /api/chat/{id}/cancel`
- Fixed: SQLAlchemy 2.0.49 `session.exec()` API change (`.bindparams()`)

**Verified:** `curl -X POST /api/chat` returns AG-UI SSE events from DeepSeek ✅

### Phase 2 — Frontend: TDesign Chat Integration  ✅

- Added `@tdesign-vue-next/chat@^0.5.2` and `splitpanes@^4.1.2`
- Created `ChatView.vue` with `<Chatbot protocol="agui">` 
- Created `stores/chat.ts` (session list/create/delete/select)
- Added `/chat` route to `router.ts`
- Added "Chat" nav link to `Sidebar.vue`
- TDesign CSS variable overrides in `style.css` (dark theme mapping)
- Fixed: `onRequest` maps TDesign Chat format (`prompt`/`attachments`) → AG-UI `RunAgentInput`
- Fixed: `<t-chatbot>` → `<Chatbot>` (PascalCase import)
- Removed: `tdesign-vue-next` direct import (transitive dep, Vite can't resolve)

**Verified:** Build passes, browser renders chat UI, messages stream from DeepSeek ✅

### Phase 3 — Frontend: Tool Call Cards  ✅

- Created `ToolCallWrapper.vue` (shared chrome: status lifecycle, expand/collapse)
- Created 9 domain cards: `FileReadCard`, `FileWriteCard`, `SearchCard`, `ContainerExecCard`, `ContainerSpawnCard`, `WebSearchCard`, `DelegateTaskCard`, `BlackboardCard`, `SkillToolCard`
- Created `GenericToolCard.vue` (fallback for unregistered tools)
- Registered all 21 harness tools + wildcard via `useAgentToolcall().register()`
- Fixed: API uses `{ name, component, handler }` config objects, not positional args

### Phase 4 — Multi-Pane Layout  ❌

- Refactor `App.vue` to 3-pane split layout using `splitpanes`
- Move existing views into inspector panel, keyed by `activeSessionId`
- Add session sidebar (left pane) with create/resume/delete
- Add "Chat" link to `Sidebar.vue`

**Verification:** Three resizable panes → sidebar navigates sessions → chat streams in center → inspector updates in right

### Phase 5 — Polish  ❌

- Cancel button for in-flight turns
- Message editing (edit last user message → resubmit)
- Markdown rendering for agent responses (code blocks with syntax highlighting)
- Session resume (load `GET /api/sessions/{id}/history` and populate chat)
- Message persistence after turns (AGUIAdapter doesn't save — need post-turn hook)
- Error states: disconnected, rate-limited, tool timeout
- Keyboard shortcut: `Ctrl+Enter` to send, `Escape` to cancel

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `PydanticAgentRuntime.stream_text()` uses `asyncio.run()` internally, may conflict with FastAPI's event loop | **Eliminated.** `AGUIAdapter.dispatch_request()` handles async execution internally — no `run_in_executor` bridging needed. |
| TDesign Chat depends on AG-UI protocol version — breaking changes possible | Pin `@tdesign-vue-next/chat` to `~0.5.2` (patch updates only).  AG-UI protocol is versioned; test before upgrading. |
| AG-UI protocol is relatively young (2024+) — may lack long-term stability | Apache 2.0 open-source, backed by CopilotKit, adopted by LangGraph, CrewAI, Google ADK, Microsoft Agent Framework, AWS Bedrock, and PydanticAI.  Multiple major frameworks adopting reduces abandonment risk. |
| TDesign Chat's English documentation is thinner than Chinese docs | Component API surface is small (1 main component + 2 hooks).  AG-UI protocol docs are English-first. |
| Tool call arguments may be too large for SSE event payloads | `AGUIAdapter` handles truncation internally.  Frontend provides expand-on-click for full args. |
| `@tdesign-vue-next/chat@0.5.2` depends on `tdesign-web-components@1.3.1-alpha.11` (alpha version) | Monitor for stable release.  The alpha package is only used for Web Component interop, not the Vue components themselves.  If it causes issues, pin to an earlier stable `tdesign-web-components` or file an issue upstream. |
| `marked` version conflict: project uses `^18.0.5`, TDesign Chat needs `^12.0.1` | pnpm isolates nested dependencies by default — TDesign Chat's `marked@12` won't affect the dashboard's `marked@18`.  Verify at build time; if bundling conflicts occur, add `marked` to `overrides` in `package.json`. |
| `pydantic_ai.ag_ui` (old path) is deprecated and will be removed in pydantic-ai 2.0 | Use `pydantic_ai.ui.ag_ui.AGUIAdapter` (current path).  Monitor pydantic-ai changelog for 2.0 migration. |
| Cancellation only affects tool execution, not LLM API calls | Documented limitation in §5.5.  The cancel token is checked between tool rounds.  For v1 this is acceptable; a future improvement could use `httpx` client cancellation. |

## 9. Non-Goals (Explicitly Out of Scope)

- **Web-based skill compilation UI** — the dashboard SkillsView already handles this
- **Agent configuration editing from the web** — stays in `harness.yaml` and CLI
- **Multi-user authentication** — single-user local harness; CORS is already open for dev
- **Mobile-responsive layout** — desktop-first; the TUI already covers remote/SSH use
- **Voice/audio input** — text-only for v1
- **Replacing the TUI** — the TUI (`harness_poc/tui.py`) remains the primary interface for terminal-native workflows; the web chat is an additional surface

## 10. Alternatives Considered

### A. Build custom SSE protocol + custom chat UI from scratch

**Rejected.**  Would require designing event types, building a streaming text buffer,
implementing tool call expand/collapse cards, handling markdown rendering, and
maintaining all of it.  Estimated 1 week for v1, ongoing maintenance.  AG-UI +
TDesign Chat gives us all of this for 2–3 days of integration.

### B. Vercel AI SDK + React frontend

**Rejected.**  Would require either rewriting the dashboard in React (throwing away
the Vue 3 codebase) or running a React app in an iframe.  Both are worse than
adopting a Vue-native solution.

### C. Chainlit (Python-native chat UI)

**Rejected.**  Chainlit replaces the frontend entirely — you write Python decorators
and it generates HTML.  We'd lose the existing Vue dashboard, Pinia stores, and
custom ECharts visualizations.  Better suited for quick demos than a production
harness with an existing observability layer.

### D. Deep Chat (framework-agnostic Web Component)

**Considered but deprioritized.**  Deep Chat works with Vue and supports custom
backends, but it has no native tool call visualization, no agent state sync,
and its message model is oriented toward simple Q&A rather than agentic loops.
We'd end up building most of the tool call and state infrastructure ourselves.
