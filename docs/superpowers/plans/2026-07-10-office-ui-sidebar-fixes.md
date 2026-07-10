# Office UI Sidebar Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three Office UI bugs reported by the user: the floating "Board" pill is misplaced, the left icon rail has no expand/collapse affordance, and the "New organization" modal is reportedly unusable in some environment.

**Architecture:** All changes are frontend-only (`opc/plugins/office_ui/frontend_src`). The Board toggle's state moves from `WorkspacePage` (local `useState`, unmounted whenever the user leaves the Workspace page) up to `App.tsx` so it can be triggered from the persistent left rail. The rail gains an `expanded` boolean (persisted like the existing `sidebarCollapsed` pattern) driving a CSS-only layout change via the existing `--rail-width` custom property. The org-create-modal CSS gets solid-color fallbacks in front of every `color-mix()` declaration, since `color-mix()` failing silently (unsupported engine) leaves the modal with no background/border — which matches the reported "faint dark, nothing clickable" symptom — and this was reproducible-uncertain but safe to harden regardless.

**Tech Stack:** React 19 + TypeScript (no build-time CSS preprocessor — plain CSS with custom properties), Vite dev server on :5173 proxying to the aiohttp backend on :8765.

## Global Constraints

- Match existing code style; do not reformat untouched lines (per project CLAUDE.md "surgical changes").
- Do not touch unrelated dead code even if noticed.
- Run `npm run typecheck` in `opc/plugins/office_ui/frontend_src` after each task; pre-existing errors in `components/ui/` and `@/lib/utils` are known and out of scope — only new errors in files touched by this plan count as a regression.
- Verify every visual change live via the running Vite dev server (already up on :5173, backend on :8765) using the browser — do not claim a UI fix works without seeing it render.

---

### Task 1: Move the Board toggle into the left icon rail

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx` (state + rail button, ~line 463-474 and ~line 2209-2239 and ~line 2304-2320)
- Modify: `opc/plugins/office_ui/frontend_src/workspace/WorkspacePage.tsx` (props interface ~line 207-263, destructure ~line 265-305, state ~line 316-317, effect ~line 344-349, JSX ~line 1080-1093)
- Modify: `opc/plugins/office_ui/frontend_src/workspace/workspace.css` (remove dead rules, ~line 15-65)

**Interfaces:**
- Produces: `WorkspacePageProps.boardDrawerOpen: boolean`, `WorkspacePageProps.onBoardDrawerOpenChange: (value: boolean | ((prev: boolean) => boolean)) => void`, `WorkspacePageProps.onBoardUnreadChange?: (count: number) => void` — these replace `WorkspacePage`'s internal `boardDrawerOpen` state, which was lost every time the user navigated away from the Workspace page (the component unmounts). Lifting it to `App.tsx` is required so the rail button (which lives outside `WorkspacePage`) can read/toggle it and so the drawer stays open across a page switch.

- [ ] **Step 1: Lift `boardDrawerOpen`/`boardUnread` state into `App.tsx`**

  In `App.tsx`, right after the existing `toggleSidebar` block (currently ends at line 470):

  ```tsx
  const [boardDrawerOpen, setBoardDrawerOpen] = useState(false)
  const [boardUnread, setBoardUnread] = useState(0)
  ```

- [ ] **Step 2: Insert the "Board" button into the rail, between Workspace and Office**

  In `App.tsx`, the rail nav currently reads (inside `<div className="rail-nav">`):

  ```tsx
          <button className={`rail-btn${activePage === 'workspace' ? ' active' : ''}`} onClick={() => setActivePage('workspace')} title="Workspace">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span className="rail-btn-label">Workspace</span>
            {(() => {
              const total = chatStore.channels.reduce((sum, ch) => sum + chatStore.getUnreadCount(ch.id), 0)
              return total > 0 ? <span className="rail-badge">{total > 99 ? '99+' : total}</span> : null
            })()}
          </button>
          <button className={`rail-btn${activePage === 'office' ? ' active' : ''}`} onClick={() => setActivePage('office')} title="Office">
  ```

  Insert a new button between them so the block becomes:

  ```tsx
          <button className={`rail-btn${activePage === 'workspace' ? ' active' : ''}`} onClick={() => setActivePage('workspace')} title="Workspace">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span className="rail-btn-label">Workspace</span>
            {(() => {
              const total = chatStore.channels.reduce((sum, ch) => sum + chatStore.getUnreadCount(ch.id), 0)
              return total > 0 ? <span className="rail-badge">{total > 99 ? '99+' : total}</span> : null
            })()}
          </button>
          <button className={`rail-btn${activePage === 'workspace' && boardDrawerOpen ? ' active' : ''}`} onClick={() => { setActivePage('workspace'); setBoardDrawerOpen(v => !v) }} title="Board">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M15 3v18"/></svg>
            <span className="rail-btn-label">Board</span>
            {boardUnread > 0 && <span className="rail-badge">{boardUnread > 99 ? '99+' : boardUnread}</span>}
          </button>
          <button className={`rail-btn${activePage === 'office' ? ' active' : ''}`} onClick={() => setActivePage('office')} title="Office">
  ```

- [ ] **Step 3: Pass the lifted state down to `WorkspacePage`**

  In `App.tsx`, the `<WorkspacePage` call currently starts:

  ```tsx
        <WorkspacePage
          boardStore={boardStore}
          chatStore={chatStore}
          sessionStore={sessionStore}
          agents={swarmAgents}
          officeMap={officeMap}
  ```

  Change to:

  ```tsx
        <WorkspacePage
          boardStore={boardStore}
          chatStore={chatStore}
          sessionStore={sessionStore}
          agents={swarmAgents}
          officeMap={officeMap}
          boardDrawerOpen={boardDrawerOpen}
          onBoardDrawerOpenChange={setBoardDrawerOpen}
          onBoardUnreadChange={setBoardUnread}
  ```

- [ ] **Step 4: Accept the new props in `WorkspacePage`**

  In `workspace/WorkspacePage.tsx`, add to `WorkspacePageProps` (right after `projectId: string`):

  ```tsx
    projectId: string
    boardDrawerOpen: boolean
    onBoardDrawerOpenChange: (value: boolean | ((prev: boolean) => boolean)) => void
    onBoardUnreadChange?: (count: number) => void
  ```

  And in the destructured function parameters (right after `projectId,`):

  ```tsx
    projectId,
    boardDrawerOpen,
    onBoardDrawerOpenChange,
    onBoardUnreadChange,
  ```

- [ ] **Step 5: Remove the local `boardDrawerOpen` state and report unread count upward**

  Delete this line (currently right after the `// ── Board drawer …` comment):

  ```tsx
  const [boardDrawerOpen, setBoardDrawerOpen] = useState(false)
  ```

  (Everything below it — `boardTasks`, `boardMaxUpdatedAt`, the seen-watermark effects, `boardUnread` — already reads the identifier `boardDrawerOpen`, which now resolves to the prop of the same name, so no other line in that block needs to change.)

  Immediately after the existing `boardUnread` `useMemo` (which ends `}, [boardDrawerOpen, boardTasks, seenMaxUpdatedAt, seenCount, boardCount])`), add:

  ```tsx
  useEffect(() => {
    onBoardUnreadChange?.(boardUnread)
  }, [boardUnread, onBoardUnreadChange])
  ```

- [ ] **Step 6: Delete the floating pill, keep the drawer wired to the lifted setter**

  Replace:

  ```tsx
      {/* Board toggle — floating pill that opens the board drawer.
          Shows a WeChat-style red badge when the board changed. */}
      <button
        className={`board-toggle${boardDrawerOpen ? ' active' : ''}`}
        onClick={() => setBoardDrawerOpen(v => !v)}
        title={boardDrawerOpen ? 'Hide board' : 'Show board'}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M15 3v18"/></svg>
        <span className="board-toggle-label">Board</span>
        {boardUnread > 0 && <span className="board-unread-badge">{boardUnread > 99 ? '99+' : boardUnread}</span>}
      </button>

      {/* Board drawer overlay backdrop */}
      {boardDrawerOpen && <div className="board-drawer-backdrop" onClick={() => setBoardDrawerOpen(false)} />}
  ```

  with:

  ```tsx
      {/* Board drawer overlay backdrop */}
      {boardDrawerOpen && <div className="board-drawer-backdrop" onClick={() => onBoardDrawerOpenChange(false)} />}
  ```

- [ ] **Step 7: Remove the now-dead CSS**

  In `workspace/workspace.css`, delete the `.board-toggle`, `.board-toggle:hover`, `.board-toggle.active`, `.board-toggle-label`, and `.board-unread-badge` rules (the block from the `/* ── Board drawer (slides over chat from the left) ── */` comment down to — but not including — the `.board-drawer-backdrop` rule). Everything from `.board-drawer-backdrop` onward stays.

- [ ] **Step 8: Verify**

  Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
  Expected: no new errors in `App.tsx` or `workspace/WorkspacePage.tsx`.

  In the browser (http://localhost:5173): open the Workspace page. Confirm there is no floating pill near "New Chat". Confirm the rail now shows Workspace → Board → Office → Org → (toggle, added in Task 2) → Dev Tools. Click the Board rail icon: the drawer should slide open and the icon should show the `active` highlight. Navigate to the Org page and back to Workspace: the drawer should still be open (state persisted). Trigger a board task update while the drawer is closed and confirm the unread badge shows on the rail icon.

- [ ] **Step 9: Commit**

  ```bash
  git add opc/plugins/office_ui/frontend_src/App.tsx opc/plugins/office_ui/frontend_src/workspace/WorkspacePage.tsx opc/plugins/office_ui/frontend_src/workspace/workspace.css
  git commit -m "fix(office-ui): move Board toggle from floating pill into the left rail"
  ```

---

### Task 2: Add expand/collapse to the left icon rail

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx` (state ~line 470, JSX ~line 2202-2239)
- Modify: `opc/plugins/office_ui/frontend_src/index.css` (`.app-shell` ~line 66-128, `.rail*` rules ~line 134-263)

**Interfaces:**
- Consumes: nothing from Task 1 except line proximity (this task's edits land just below Task 1's new `boardUnread` state line).
- Produces: `.app-shell.rail-expanded` CSS hook and `railExpanded`/`toggleRailExpanded` local state in `App.tsx`, used only within this task.

- [ ] **Step 1: Add persisted `railExpanded` state**

  In `App.tsx`, right after the `boardUnread` state added in Task 1:

  ```tsx
  const [railExpanded, setRailExpanded] = useState(() => {
    try { return localStorage.getItem('opc_rail_expanded') === '1' } catch { return false }
  })
  const toggleRailExpanded = () => setRailExpanded(v => {
    const next = !v
    try { localStorage.setItem('opc_rail_expanded', next ? '1' : '0') } catch { /* private mode */ }
    return next
  })
  ```

- [ ] **Step 2: Apply the `rail-expanded` class to `.app-shell` and `.rail`**

  Change:

  ```tsx
    return (
      <div className={`app-shell theme-${theme}`}>
  ```

  to:

  ```tsx
    return (
      <div className={`app-shell theme-${theme}${railExpanded ? ' rail-expanded' : ''}`}>
  ```

  Change:

  ```tsx
        <nav className="rail">
  ```

  to:

  ```tsx
        <nav className={`rail${railExpanded ? ' expanded' : ''}`}>
  ```

- [ ] **Step 3: Add the expand/collapse toggle button to `rail-bottom`**

  Change:

  ```tsx
        <div className="rail-bottom">
          <button className={`rail-btn${showDevTools ? ' active' : ''}`} onClick={() => setShowDevTools((v) => !v)} title="Developer Tools">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3L3 8l5 5M16 11l5 5-5 5"/></svg>
            <span className="rail-btn-label">Dev Tools</span>
          </button>
        </div>
  ```

  to:

  ```tsx
        <div className="rail-bottom">
          <button className="rail-btn" onClick={toggleRailExpanded} title={railExpanded ? 'Collapse' : 'Expand'}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              {railExpanded ? <path d="M15 6l-6 6 6 6"/> : <path d="M9 6l6 6-6 6"/>}
            </svg>
            <span className="rail-btn-label">{railExpanded ? 'Collapse' : 'Expand'}</span>
          </button>
          <button className={`rail-btn${showDevTools ? ' active' : ''}`} onClick={() => setShowDevTools((v) => !v)} title="Developer Tools">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3L3 8l5 5M16 11l5 5-5 5"/></svg>
            <span className="rail-btn-label">Dev Tools</span>
          </button>
        </div>
  ```

- [ ] **Step 4: CSS — animate the rail width via the existing `--rail-width` variable**

  In `index.css`, inside the `.app-shell { ... }` rule, `--rail-width: 60px;` already exists (line 118). Add a new rule right after the `.app-shell { ... }` block closes:

  ```css
  .app-shell.rail-expanded {
    --rail-width: 176px;
  }
  ```

- [ ] **Step 5: CSS — make `.rail` and `.rail-btn` respect the variable and transition smoothly**

  Change the `.rail` rule from:

  ```css
  .rail {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 12px 0;
    background: rgba(255, 255, 255, 0.72);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-right: 1px solid var(--border);
    overflow: hidden;
  }
  ```

  to:

  ```css
  .rail {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 12px 0;
    width: var(--rail-width);
    background: rgba(255, 255, 255, 0.72);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-right: 1px solid var(--border);
    overflow: hidden;
    transition: width 200ms ease;
  }
  ```

- [ ] **Step 6: CSS — expanded layout for nav buttons and labels**

  Add after the existing `.rail-badge { ... }` rule (the last rule in the current `.rail*` group, ends around line 263):

  ```css
  .rail.expanded .rail-nav,
  .rail.expanded .rail-bottom {
    width: 100%;
    padding: 0 10px;
    box-sizing: border-box;
  }

  .rail.expanded .rail-btn {
    width: 100%;
    justify-content: flex-start;
    padding: 0 12px;
    gap: 12px;
  }

  .rail.expanded .rail-btn.active::before {
    display: none;
  }

  .rail.expanded .rail-btn-label {
    position: static;
    opacity: 1;
    pointer-events: auto;
    transform: none;
    background: none;
    color: inherit;
    box-shadow: none;
    padding: 0;
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    z-index: auto;
  }

  .rail.expanded .rail-badge {
    position: static;
    margin-left: auto;
    box-shadow: none;
  }
  ```

  This leaves the default (collapsed, no `.expanded` class) rail pixel-for-pixel identical to today: icon-only buttons, hover tooltip labels, no layout change. Only `.rail.expanded` opts into the wide, label-visible layout.

- [ ] **Step 7: Verify**

  Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
  Expected: no new errors in `App.tsx`.

  In the browser: click the new expand/collapse button at the bottom of the rail. Confirm the rail widens smoothly and every icon (Workspace, Board, Office, Org, the toggle itself, Dev Tools) shows its text label inline, left-aligned next to the icon. Click again: confirm it shrinks back to exactly today's icon-only look, with hover tooltips still working. Confirm the toggle state is not lost on page reload (persisted via `localStorage`).

- [ ] **Step 8: Commit**

  ```bash
  git add opc/plugins/office_ui/frontend_src/App.tsx opc/plugins/office_ui/frontend_src/index.css
  git commit -m "feat(office-ui): add expand/collapse toggle to the left icon rail"
  ```

---

### Task 3: Harden the "New organization" modal against `color-mix()` failures

**Context:** Live-tested `OrgCreateModal` in the Modern and Midnight themes on the running dev server — it rendered and behaved correctly in both. Root cause could not be reproduced. Per the user's instruction to fix it based on best understanding: every background/border color in this modal is built with CSS `color-mix()`. If the runtime rendering this UI doesn't support `color-mix()` (older WebView/Electron build, embedded browser, etc.), each of those declarations is dropped entirely at parse time, leaving the element with no background/border and inheriting whatever is behind it — a dark, uncolored shape that visually matches "faint dark, nothing looks right." This task adds a plain solid-color fallback (using the same CSS variables, without the alpha-blend) directly before every `color-mix()` declaration in the modal's CSS. CSS resolves duplicate properties by taking the last one that's valid, so modern browsers are unaffected (they still get the blended `color-mix()` result) while any engine without `color-mix()` support now gets a theme-correct solid color instead of nothing.

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/org/org.css` (lines 413-691, the `/* ── Create Organization Modal ── */` block)

**Interfaces:** None — pure CSS, no new selectors or variables beyond the existing theme custom properties already defined for every theme in `index.css`.

- [ ] **Step 1: Backdrop and modal shell**

  ```css
  .org-create-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: rgba(5, 7, 11, 0.68);
    background: color-mix(in srgb, #05070b 68%, transparent);
  }

  .org-create-modal {
    width: min(720px, 100%);
    max-height: min(720px, calc(100vh - 48px));
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    border: 1px solid var(--border);
    border: 1px solid color-mix(in srgb, var(--border) 78%, transparent);
    border-radius: 8px;
    background: var(--bg-elevated);
    background:
      linear-gradient(180deg,
        color-mix(in srgb, var(--bg-elevated) 88%, var(--bg) 12%),
        color-mix(in srgb, var(--bg) 94%, var(--bg-elevated) 6%));
    box-shadow: 0 28px 80px rgb(0 0 0 / 0.46);
    overflow: hidden;
  }
  ```

- [ ] **Step 2: Close/icon buttons**

  ```css
  .org-create-close,
  .org-create-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border);
    border: 1px solid color-mix(in srgb, var(--border) 78%, transparent);
    border-radius: 6px;
    background: var(--bg);
    background: color-mix(in srgb, var(--bg) 60%, transparent);
    color: var(--text-secondary);
    cursor: pointer;
  }

  .org-create-close {
    width: 30px;
    height: 30px;
    font-size: 14px;
  }

  .org-create-close:hover,
  .org-create-icon-btn:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--border);
    border-color: color-mix(in srgb, var(--text-secondary) 34%, var(--border));
  }
  ```

- [ ] **Step 3: Step indicator pills**

  ```css
  .org-create-step {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    min-height: 34px;
    padding: 7px 10px;
    border: 1px solid var(--border);
    border: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
    border-radius: 7px;
    background: var(--bg);
    background: color-mix(in srgb, var(--bg) 58%, transparent);
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 600;
  }

  .org-create-step span {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--border);
    background: color-mix(in srgb, var(--text-secondary) 12%, transparent);
    color: var(--text-secondary);
    font-size: 10px;
  }

  .org-create-step--active {
    border-color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
    color: var(--text);
    background: var(--bg);
    background: color-mix(in srgb, var(--accent) 9%, var(--bg) 91%);
  }

  .org-create-step--active span,
  .org-create-step--done span {
    background: var(--accent);
    background: color-mix(in srgb, var(--accent) 24%, transparent);
    color: var(--accent);
  }
  ```

- [ ] **Step 4: Form fields**

  ```css
  .org-create-field input,
  .org-create-member-row input,
  .org-create-member-row select,
  .org-create-member-row textarea {
    min-height: 38px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border: 1px solid color-mix(in srgb, var(--border) 82%, transparent);
    border-radius: 7px;
    background: var(--bg);
    background: color-mix(in srgb, var(--bg) 64%, transparent);
    color: var(--text);
    font: inherit;
    font-size: 13px;
    outline: none;
  }

  .org-create-field input:focus,
  .org-create-member-row input:focus,
  .org-create-member-row select:focus,
  .org-create-member-row textarea:focus {
    border-color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  }
  ```

- [ ] **Step 5: Add-member button, review rows, error box**

  ```css
  .org-create-add {
    margin-top: 12px;
    min-height: 34px;
    padding: 7px 12px;
    border: 1px dashed var(--accent);
    border: 1px dashed color-mix(in srgb, var(--accent) 34%, var(--border));
    border-radius: 7px;
    background: transparent;
    background: color-mix(in srgb, var(--accent) 7%, transparent);
    color: var(--accent);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
  }

  .org-create-review-head,
  .org-create-review-row {
    justify-content: space-between;
    gap: 14px;
    min-height: 38px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border: 1px solid color-mix(in srgb, var(--border) 74%, transparent);
    border-radius: 7px;
    background: var(--bg);
    background: color-mix(in srgb, var(--bg) 56%, transparent);
  }

  .org-create-review-row em {
    padding: 2px 6px;
    border-radius: 999px;
    background: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent);
    font-style: normal;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
  }

  .org-create-error {
    padding: 9px 11px;
    border: 1px solid var(--red);
    border: 1px solid color-mix(in srgb, var(--red) 28%, transparent);
    border-radius: 7px;
    background: var(--red);
    background: color-mix(in srgb, var(--red) 10%, transparent);
    color: var(--red);
    font-size: 12px;
  }
  ```

  Note: several of these fallback values (e.g. `.org-create-add` background falling back to fully-opaque `var(--accent)`, `.org-create-error` background falling back to fully-opaque `var(--red)`) are visually stronger than the intended faint tint. That's an intentional tradeoff — a too-saturated fallback is still fully legible and clickable, whereas today's failure mode (no background at all) is not. Do not try to hand-tune these to match the `color-mix()` result exactly; the goal is "always renders correctly," not "renders identically."

- [ ] **Step 6: Verify — regression-check both themes still look right**

  In the browser: open Org → New organization in the Modern theme, then switch to Midnight and reopen. Step through Name → Members → Review in both. Confirm nothing looks different from before this task (the fallback lines should be invisible in a browser that supports `color-mix()` — the last declaration always wins).

  Run: `cd opc/plugins/office_ui/frontend_src && npx tsx --test org/OrgTab.test.tsx` (existing test reads `OrgCreateModal.tsx` source text — confirm it still passes since this task only touches CSS, not the `.tsx` file).

- [ ] **Step 7: Commit**

  ```bash
  git add opc/plugins/office_ui/frontend_src/org/org.css
  git commit -m "fix(office-ui): add solid-color fallbacks before color-mix() in the org-create modal"
  ```

---

### Task 4: Final cross-check

- [ ] **Step 1: Full typecheck**

  Run: `cd opc/plugins/office_ui/frontend_src && npm run typecheck`
  Expected: no errors in any file touched by Tasks 1-3 (pre-existing unrelated errors in `components/ui/` / `@/lib/utils` are out of scope).

- [ ] **Step 2: Full manual browser pass**

  On http://localhost:5173, with the backend on :8765 already running:
  - Rail collapsed (default): only icons visible, hover shows tooltip labels, Board icon sits between Workspace and Office.
  - Rail expanded: click the toggle at the bottom of the rail — all labels appear inline, rail widens, toggle icon flips direction.
  - Click Board from any page (Office, Org): jumps to Workspace and opens the drawer.
  - Board unread badge appears/clears correctly (create a task on the board while the drawer is closed, confirm the badge shows on the rail icon; open the drawer, confirm it clears).
  - New organization modal: open in at least 2 themes, confirm all steps (Name/Members/Review) are legible and every button/input is clickable.

- [ ] **Step 3: Report to user**

  Summarize what changed and ask the user to confirm the org-create-modal fix actually resolves what they saw, since it could not be reproduced during planning — if it's still broken in their environment, we'll need a screenshot or browser/version info to diagnose further.
