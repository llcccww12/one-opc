# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OpenOPC ("One-Person Company") is a Python orchestration runtime that assembles AI agents into a company-like structure to execute complex tasks — plus a React+Phaser "Office UI" frontend and a Typer-based CLI. Two execution modes matter everywhere in the code: **Task Mode** (single agent/session, LobeChat-like) and **Company Mode** (a brief compiled into a role-owned work-item graph, executed by a simulated org). Some lower-level CLI/service code still calls Company-Mode-with-a-saved-architecture `org` for historical reasons — in the UI/README this is just "Company + architecture choice".

## Commands

### Backend (Python, `>=3.10`)

```bash
python -m pip install -e .              # install in editable mode (or: uv pip install -e .)
python -m pytest                        # run full test suite (tests/)
python -m pytest tests/test_cli_app.py::CliInitProjectTests::test_external_agent_preflight_accepts_fake_agent_binaries  # single test
python -m pytest tests/test_company_collaboration.py -q   # single file
opc init                                # one-time: creates .opc/, copies config templates
opc ui                                  # launch Office UI (aiohttp server + auto-built frontend), http://localhost:8765
opc ui --rebuild                        # force frontend rebuild
opc chat -p demo --mode task --agent native "..."      # interactive/one-shot Task Mode
opc chat -p demo --mode company --company-profile corporate "..."  # Company Mode
opc exec -p demo --mode task --agent codex --json "..." # non-interactive/CI-style
```

There is no ruff/mypy/flake8 config in this repo — no separate lint command exists. Tests live under `tests/` (mirrors package structure, e.g. `tests/test_company_collaboration.py`) with fixtures in `tests/fixtures/` and e2e specs in `tests/e2e/`.

### Frontend (`opc/plugins/office_ui/frontend_src`, Node `>=18`)

```bash
cd opc/plugins/office_ui/frontend_src
npm install
npm run dev          # vite dev server on :5173, proxies /ws and /api to :8765
npm run typecheck    # tsc -b — run this after any change, the repo has pre-existing unrelated errors in components/ and @/lib/utils so filter by changed file
npm run build        # outputs to ../frontend_dist (served by opc ui)
```

There is no aggregate frontend test script. Tests are plain `node:assert` + `node:test` files (`*.test.ts`/`*.test.tsx`) run directly via `tsx`, often by asserting on the *source text* of the file under test rather than mounting components:

```bash
npx tsx --test workspace/WorkspacePage.test.ts          # single test file
npx tsx --test chat/ChatStore.test.ts kanban/BoardStore.test.ts App.test.tsx   # a few together
```

`opc ui` auto-rebuilds the frontend when `frontend_src` is newer than `frontend_dist` (mtime check in `opc/plugins/office_ui/__init__.py`), so a manual `npm run build` is usually only needed when iterating without restarting `opc ui`.

## Architecture

### Backend: seven layers, one engine

`opc/engine.py` (`OPCEngine`) is the central orchestrator wiring together seven layers, each its own top-level package:

| Layer | Package | Responsibility |
|---|---|---|
| 0 | `opc/layer0_interaction` | Message bus connecting CLI, Office UI, and external channels |
| 1 | `opc/layer1_perception` | Context loading/assembly, task routing |
| 2 | `opc/layer2_organization` | Work-item planning, Company Mode runtime, comms, escalation, approval, recovery, recruitment (`org_engine.py`, `company_mode.py`, `custom_runtime.py`, `collaboration_service.py`) |
| 3 | `opc/layer3_agent` | Native agent runtime, external agent adapters (`adapters/`), permission/tool planning, `runtime_v2/` |
| 4 | `opc/layer4_tools` | Shell, file ops, browser (Playwright), web search, Python exec, git, collaboration tools — all registered through `registry.py` |
| 5 | `opc/layer5_memory` | Markdown memory, session compaction, employee evolution/preferences, skill library/import |
| 6 | `opc/layer6_observability` | Event bus consumers, cost tracking, structured logging |

`opc/core/` holds cross-layer primitives (`models.py` — the shared dataclasses like `Task`, `DelegationWorkItem`, `OPCEvent`; `config.py` — `OPCConfig`, `get_opc_home()`, project/workplace path resolution; `org_config.py`, `attachment_store.py`, `company_tools.py`).

Company Mode's core mechanism: a brief is decomposed into a work-item dependency DAG; a manager role executes/delegates/reviews/integrates/reworks items across role-owned sessions; independent items run in parallel, dependent ones wait; blockers pause the sender and either activate a peer role or escalate to the human owner. All of this is mirrored live to the UI (kanban, chat progress cards, Agents/Comms/Team tabs).

### State on disk (not in the repo)

- `.opc/config/*.yaml` — LLM keys, system/agent/channel config, company architectures (`company_corporate_config.yaml` built-in, `company_orgs/org_<id>_config.yaml` saved/custom)
- `.opc/memory/`, `.opc/projects/<project>/`, `.opc/ui_state.db` (Office UI chat/agent/visual state)
- `../OpenOPC_workplace/<project>/` — where agents write durable deliverables; `.opc-comms/` inside it holds company-mode mailboxes/meetings
- `OPC_HOME` env var relocates `.opc/` outside the repo

### Office UI plugin (`opc/plugins/office_ui/`)

This is a self-contained plugin registered into the Typer app via `register_cli()` (see bottom of `opc/cli/app.py`), only if `aiohttp`/`aiosqlite` are importable.

- `server.py` — aiohttp server; boots `OPCEngine`, opens `ui_state.db`, wires `EventAdapter` → `WSHandler`, serves the built frontend as static files plus the `/ws` WebSocket endpoint.
- `ws_handler.py` — **the message router** (huge file, ~10k lines): one `_handle_<type>` method per WS request type, delegating to `services/*.py` (thin per-domain service modules: `agent.py`, `kanban.py`, `session.py`, `org.py`, `talent.py`, `market.py`, `comms.py`, `runtime.py`, `work_item.py`, `project.py`, `context.py`, wired together in `factory.py`).
- `event_adapter.py` — translates `OPCEngine` event-bus events into UI-facing WS pushes (`snapshot`, `org_info`, `board_task_*`, `session_progress`, etc.).
- `chat_store.py` / `agent_store.py` — SQLite-backed persistence for chat channels/messages and visual agent/office state.
- `snapshot_builder.py` — builds the full visual-state snapshot sent to newly-connected clients.
- `dispatcher.py`, `recovery_manager.py`, `execution_identity.py`, `org_architecture_snapshot.py` — supporting glue for dispatch, crash recovery, and identity resolution between runtime sessions and UI tasks.

**`docs/FRONTEND_BACKEND_MAP.md` is the authoritative map of every WS request type → handler → service → response type**, grouped by feature area (projects, sessions, agents, execution mode, kanban, org, ...). Read it before adding or changing any WS contract — frontend and backend must stay in lockstep on request/response `type` strings, since there is no shared schema layer between them.

### Frontend (`opc/plugins/office_ui/frontend_src/`)

React 19 + Vite + Tailwind v4 + shadcn, driven entirely by one WebSocket connection (`lib/` client, ~60 methods) — the frontend is a pure display layer over engine state, no business logic of its own.

- `App.tsx` — the hub: owns the WS client ref, top-level page switch (`workspace` / `office` / `org` / `mapEditor`), the left icon nav rail (`.rail`), theme (`theme-${name}` class, 8 themes defined in `index.css`), and the office Phaser canvas + team sidebar (`.main-grid`).
- `workspace/WorkspacePage.tsx` — the default page: session sidebar, a slide-out kanban board drawer (`.board-drawer`, toggled by the floating "board" pill with a WeChat-style unread badge), and the chat `ContextPanel` (tabs: Chat/Agents/Info/Comms/Team).
- Stores (`stores/`, `chat/ChatStore.ts`, `kanban/BoardStore.ts`) hold client-side state normalized from WS pushes — e.g. `ChatStore` computes `unreadCounts` from `readTimestamps`; anything that calls `markRead()` unconditionally inside a `useEffect` risks an infinite re-render loop because `markRead` stamps a fresh `Date.now()` each call (guard with `getUnreadCount() > 0` first).
- `org/` — company architecture editor (role graph/table, saved-org switcher, marketplace/presets, import/export YAML).
- `kanban/`, `chat/` — presentational components for the board and conversation surfaces; `game/` — the Phaser-driven animated office map.
- CSS is per-feature (`index.css` for shell/theme tokens, `workspace/workspace.css`, `kanban/kanban.css`, `chat/chat.css`, `org/*.css`) using a single CSS-variable theme system on `.app-shell` (`--bg`, `--surface`, `--accent`, `--radius*`, `--shadow*`) — prefer extending these variables/classes over introducing new ad-hoc colors, and check both `index.css` and the feature-specific CSS file for a class name before assuming which one wins (later `@import`s can silently shadow earlier rules with the same selector).

### CLI (`opc/cli/app.py`)

Single large Typer app (`opc`); command groups map roughly 1:1 to backend concepts: `project`, `session`, `mode`, `kanban`, `agent`, `org`, `talent`, `market`, `runtime`, `recovery`, `channels`. `opc chat`/`opc exec` are the natural-language entrypoints; everything else is lower-level inspection/scripting support. See `docs/cli-chat-slash.md` for the interactive slash-command table available inside `opc chat`.

### Channels (`opc/channels/`)

Each external messaging provider (Slack, Discord, Telegram, Feishu, DingTalk, Matrix, QQ, WhatsApp, Mochat, Email) is an optional extra (`pip install -e .[channels-<name>]`) implementing a common provider interface (`provider_base.py`, registered in `provider_registry.py`) and routed through `manager.py` into the same `layer0_interaction` message bus the CLI/UI use — channels are just another interaction surface, not a separate execution path.
