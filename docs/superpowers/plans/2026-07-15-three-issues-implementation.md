# 三问题实现计划：状态徽章 + 审核面板 + 云主机执行

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复三个问题——(1) 状态徽章不可区分、(2) 审核卡死无人工介入、(3) Company Mode 不在云主机执行。

**Architecture:** 纯前端改动 + 后端 WS handler 扩展 + 执行路径路由层插入。三个问题互相独立，按 1→3→2 顺序实施。

**Tech Stack:** React 19 + TypeScript (frontend), Python asyncio + aiohttp (backend), WebSocket 双向通信。

## Global Constraints

- 前端改动后需 `npm run typecheck` 通过（仅检查改动文件，repo 有 pre-existing 无关错误）
- 后端改动后需 `python -m pytest` 通过
- inline SVG 图标遵循 `SvgIcons.tsx` 的 16×16 viewBox 0 0 24 24 stroke currentColor 1.5 规范
- WS 消息类型字符串使用 snake_case
- CSS 颜色复用现有 CSS 变量 `--green`, `--yellow`, `--red`, `--text-dim`

---

## Issue 1：状态徽章重设计

### Task 1.1: 新建 StatusIcons 组件

**Files:**
- Create: `opc/plugins/office_ui/frontend_src/components/StatusIcons.tsx`

**Interfaces:**
- Produces: `IconSignal()`, `IconCloud()`, `IconKey()` — React 组件，16×16 inline SVG

- [ ] **Step 1: 创建 StatusIcons.tsx**

```tsx
// opc/plugins/office_ui/frontend_src/components/StatusIcons.tsx
/**
 * Status indicator icons for the rail sidebar.
 * Geometry derived from Lucide (https://lucide.dev), MIT.
 * 16×16, stroke currentColor 1.5, round caps & joins.
 */

import React from 'react'

/** Signal / WiFi icon — represents WebSocket connection status */
export function IconSignal() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 20h.01" />
      <path d="M7 20v-4" />
      <path d="M12 20v-8" />
      <path d="M17 20V8" />
      <path d="M22 4v16" />
    </svg>
  )
}

/** Cloud icon — represents VM / cloud host status */
export function IconCloud() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
    </svg>
  )
}

/** Key icon — represents LLM API key status */
export function IconKey() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4" />
      <path d="m21 2-9.6 9.6" />
      <circle cx="7.5" cy="15.5" r="5.5" />
    </svg>
  )
}
```

- [ ] **Step 2: 验证文件创建成功**

Run: `ls -la opc/plugins/office_ui/frontend_src/components/StatusIcons.tsx`
Expected: 文件存在

- [ ] **Step 3: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/components/StatusIcons.tsx
git commit -m "feat: add StatusIcons component with Signal/Cloud/Key icons"
```

---

### Task 1.2: 替换 App.tsx 中的 conn-dot 为 StatusIcons

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx:2335-2339` (rail-top JSX)
- Modify: `opc/plugins/office_ui/frontend_src/App.tsx:2415-2421` (LLM key stat-chip)

**Interfaces:**
- Consumes: `IconSignal`, `IconCloud`, `IconKey` from `components/StatusIcons`
- Produces: 三个带图标的 `.status-indicator` 元素替代原 `.conn-dot`

- [ ] **Step 1: 在 App.tsx 顶部添加 import**

在 App.tsx 的 import 区域（文件顶部）添加：

```tsx
import { IconSignal, IconCloud, IconKey } from './components/StatusIcons'
```

- [ ] **Step 2: 替换 .rail-top 中的两个 conn-dot (L2335-2339)**

将：

```tsx
<span className="rail-logo" title="OpenOPC">O</span>
<div className={`conn-dot ${statusClass(status)}`} title={`${status}${statusDetail ? ` — ${statusDetail}` : ''}\n${wsUrl}`} />
<div className={`conn-dot ${vmStatusClass(vmStatus?.status)}`} title={vmStatusLabel(vmStatus)} />
```

替换为：

```tsx
<span className="rail-logo" title="OpenOPC">O</span>
<div className={`status-indicator ${statusClass(status)}`} title={`${status}${statusDetail ? ` — ${statusDetail}` : ''}\n${wsUrl}`}>
  <IconSignal />
  <span className="status-dot" />
</div>
<div className={`status-indicator ${vmStatusClass(vmStatus?.status)}`} title={vmStatusLabel(vmStatus)}>
  <IconCloud />
  <span className="status-dot" />
</div>
<div className={`status-indicator ${llmConfig?.api_key_set ? 'ok' : 'warn'}`} title={llmConfig?.api_key_set ? `LLM API Key: 已配置\nBase: ${llmConfig.api_base || '(default)'}` : 'LLM API Key: 未配置'}>
  <IconKey />
  <span className="status-dot" />
</div>
```

- [ ] **Step 3: 移除 stat-chip 中的 LLM conn-dot (L2415-2421)**

将：

```tsx
<span
  className="stat-chip"
  title={llmConfig?.api_key_set ? `Base: ${llmConfig.api_base || '(default)'}` : '未配置 API Key —— 点击左下角头像进入设置'}
>
  <span className={`conn-dot ${llmConfig?.api_key_set ? 'ok' : 'warn'}`} />
  {llmConfig?.default_model || '未设置模型'}
</span>
```

替换为：

```tsx
<span
  className="stat-chip"
  title={llmConfig?.api_key_set ? `Base: ${llmConfig.api_base || '(default)'}` : '未配置 API Key —— 点击左下角头像进入设置'}
>
  {llmConfig?.api_key_set ? '✓' : '✗'} {llmConfig?.default_model || '未设置模型'}
</span>
```

- [ ] **Step 4: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/App.tsx
git commit -m "feat: replace conn-dots with icon-based status indicators in rail sidebar"
```

---

### Task 1.3: 添加 .status-indicator CSS 样式

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/index.css:153-160` (rail-top)
- Modify: `opc/plugins/office_ui/frontend_src/index.css:787-807` (conn-dot → status-indicator)

**Interfaces:**
- Produces: `.status-indicator` CSS class with icon + dot layout, color states

- [ ] **Step 1: 修改 .rail-top 样式 (L153-160)**

将：

```css
.rail-top {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding-bottom: 10px;
  margin-bottom: 4px;
}
```

替换为：

```css
.rail-top {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding-bottom: 10px;
  margin-bottom: 4px;
}
```

- [ ] **Step 2: 在 .conn-dot 规则之后添加 .status-indicator 样式 (L807 之后)**

在 `.conn-dot.error { background: var(--red); }` 之后添加：

```css
/* Status indicator: icon + colored dot, used in rail-top */
.status-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: default;
  opacity: 0.7;
  transition: opacity 150ms ease;
}

.status-indicator:hover {
  opacity: 1;
}

.status-indicator svg {
  color: var(--text-dim);
  flex-shrink: 0;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-dim);
  flex-shrink: 0;
}

.status-indicator.ok svg { color: var(--green); }
.status-indicator.ok .status-dot {
  background: var(--green);
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
  animation: pulse-green 2s infinite;
}

.status-indicator.warn svg { color: var(--yellow); }
.status-indicator.warn .status-dot { background: var(--yellow); }

.status-indicator.error svg { color: var(--red); }
.status-indicator.error .status-dot { background: var(--red); }
```

- [ ] **Step 3: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/index.css
git commit -m "feat: add status-indicator CSS styles for icon-based rail badges"
```

---

### Task 1.4: TypeScript 验证

**Files:**
- No file changes

- [ ] **Step 1: 运行 typecheck**

Run: `cd opc/plugins/office_ui/frontend_src && npx tsc -b --noEmit 2>&1 | grep -E "StatusIcons|App\.tsx" || echo "No type errors in changed files"`
Expected: No type errors related to StatusIcons or App.tsx

- [ ] **Step 2: 如有错误则修复并 commit**

---

## Issue 3：审核面板

### Task 3.1: 修改 company_mode.py 激活 AWAITING_HUMAN 路径

**Files:**
- Modify: `opc/layer2_organization/company_mode.py:7058` 附近 (`_finalize_review_work_item`)

**Interfaces:**
- Produces: 当 gate-harness 返回 `escalate` 或 rework 次数达到 stagnation cap 时，`next_phase` 设为 `AWAITING_HUMAN`
- 使 `_save_review_rework_human_checkpoint` (L7645-7734) 变为可达代码

- [ ] **Step 1: 定位修改点**

在 `company_mode.py` 的 `_finalize_review_work_item` 方法中，找到设置 `next_phase` 的逻辑（~L7058）。当前逻辑大致为：

```python
if gate_verdict == 'pass':
    next_phase = Phase.APPROVED
elif gate_verdict == 'rework_same_work_item':
    next_phase = Phase.READY_FOR_REWORK
else:  # 'escalate' — 当前继续 AI 审核循环
    next_phase = Phase.APPROVED  # 或其他 AI 审核路径
```

- [ ] **Step 2: 修改 escalate 分支**

将 `escalate` 分支改为：

```python
if gate_verdict == 'pass':
    next_phase = Phase.APPROVED
elif gate_verdict == 'rework_same_work_item':
    next_phase = Phase.READY_FOR_REWORK
else:  # 'escalate'
    next_phase = Phase.AWAITING_HUMAN
```

- [ ] **Step 3: 修改 auto-approve 逻辑**

找到 `auto_done_rework_cap` 相关的自动通过逻辑（~L7088-7100）。当 rework 次数达到上限时，不再静默 auto-approve，而是先设为 `AWAITING_HUMAN`：

```python
# 原逻辑：rework_count >= max_review_reworks → auto_approve
# 改为：rework_count >= max_review_reworks → AWAITING_HUMAN
if rework_count >= self.max_review_reworks:
    next_phase = Phase.AWAITING_HUMAN
```

- [ ] **Step 4: 确认 human checkpoint 调用**

确认在 `next_phase == Phase.AWAITING_HUMAN` 的分支中，`_save_review_rework_human_checkpoint` 被调用（L7123-7127）。如果该调用被条件守卫，确保守卫条件匹配。

- [ ] **Step 5: 运行测试**

Run: `cd /Users/laiweichao/Documents/OpenOPC-main && python -m pytest tests/ -q --tb=short 2>&1 | tail -20`
Expected: 所有现有测试通过（或仅有 pre-existing 失败）

- [ ] **Step 6: Commit**

```bash
git add opc/layer2_organization/company_mode.py
git commit -m "feat: activate AWAITING_HUMAN phase for escalated review items"
```

---

### Task 3.2: 添加 review_decision WS handler

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py:10050-10138` (dispatch map)
- Modify: `opc/plugins/office_ui/ws_handler.py` — 新增 `_handle_review_decision` 方法

**Interfaces:**
- Consumes: `data.work_item_id: str`, `data.decision: 'approve'|'reject'|'rework'`, `data.feedback: str|None`
- Produces: work-item phase 变更 + board 更新广播

- [ ] **Step 1: 在 ws_handler.py 中添加 _handle_review_decision 方法**

在 ws_handler.py 中合适位置（其他 `_handle_*` 方法附近）添加：

```python
async def _handle_review_decision(self, ws: Any, data: dict) -> None:
    """Handle human review decision for a work item in AWAITING_HUMAN phase."""
    work_item_id = data.get("work_item_id") or ""
    decision = data.get("decision") or ""
    feedback = (data.get("feedback") or "").strip()

    if not work_item_id or decision not in ("approve", "reject", "rework"):
        await self._send_error(ws, "review_decision requires work_item_id and decision (approve/reject/rework)")
        return

    # Find the work item via the company runtime
    project_id = data.get("project_id") or self._current_project_id
    if not project_id:
        await self._send_error(ws, "review_decision requires project_id")
        return

    engine = self._resolve_engine(project_id)
    if engine is None:
        await self._send_error(ws, "no engine for project")
        return

    # Access company runtime to find and update the work item
    company_runtime = getattr(engine, '_company_runtime', None)
    if company_runtime is None:
        await self._send_error(ws, "no company runtime active")
        return

    work_item = company_runtime.get_work_item(work_item_id)
    if work_item is None:
        await self._send_error(ws, f"work item {work_item_id} not found")
        return

    from opc.layer2_organization.phase import Phase
    current_phase = getattr(work_item, 'phase', None)
    if current_phase not in (Phase.AWAITING_HUMAN, Phase.AWAITING_MANAGER_REVIEW):
        await self._send_error(ws, f"work item is in phase {current_phase}, not awaiting review")
        return

    if decision == "approve":
        work_item.phase = Phase.APPROVED
    elif decision == "reject":
        work_item.phase = Phase.FAILED
    elif decision == "rework":
        work_item.phase = Phase.READY_FOR_REWORK
        if feedback:
            # Inject feedback into work item context for the next rework iteration
            if hasattr(work_item, 'review_feedback'):
                work_item.review_feedback = feedback
            elif hasattr(work_item, 'context'):
                ctx = work_item.context or {}
                ctx['rework_feedback'] = feedback
                work_item.context = ctx

    # Broadcast board update
    await self._broadcast_work_item_update(project_id, work_item)

    # Send ack
    await self._send_json(ws, {
        "type": "review_decision_ack",
        "work_item_id": work_item_id,
        "decision": decision,
        "new_phase": str(work_item.phase),
    })
```

- [ ] **Step 2: 注册到 dispatch map**

在 `_HANDLERS` dict 中添加条目（L10050-10138 区域），或在文件底部追加：

```python
_HANDLERS["review_decision"] = _handle_review_decision
```

- [ ] **Step 3: 运行测试**

Run: `cd /Users/laiweichao/Documents/OpenOPC-main && python -m pytest tests/ -q --tb=short 2>&1 | tail -20`
Expected: 无新增失败

- [ ] **Step 4: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py
git commit -m "feat: add review_decision WS handler for human approval/rejection/rework"
```

---

### Task 3.3: 添加 review_required WS 推送

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py` — 在 work-item 进入 `AWAITING_HUMAN` 时推送事件

**Interfaces:**
- Produces: `self.broadcast({"type": "review_required", "payload": {...}})` 消息

- [ ] **Step 1: 在 company_mode.py 的 AWAITING_HUMAN 分支中添加广播调用**

在 `_finalize_review_work_item` 中，当 `next_phase` 被设为 `AWAITING_HUMAN` 后，添加事件推送。由于 company_mode 不能直接访问 ws_handler 的 broadcast，通过 event bus 发布事件：

在 company_mode.py 的 `_finalize_review_work_item` 中，`next_phase = Phase.AWAITING_HUMAN` 之后：

```python
# Emit event for UI notification
if hasattr(self, '_event_bus') and self._event_bus:
    self._event_bus.emit('review_required', {
        'work_item_id': work_item.id if hasattr(work_item, 'id') else str(work_item),
        'title': getattr(work_item, 'title', ''),
        'role_name': getattr(work_item, 'role_name', ''),
        'project_id': self._project_id,
    })
```

- [ ] **Step 2: 在 ws_handler.py 中监听 review_required 事件并广播**

在 ws_handler.py 的事件监听区域（搜索 `event_bus.on` 或 `addEventListener` 模式），添加：

```python
# 在 engine 初始化或 ws_handler 初始化时注册
if hasattr(engine, '_event_bus') and engine._event_bus:
    engine._event_bus.on('review_required', lambda data: self._track(
        self.broadcast({"type": "review_required", "payload": data})
    ))
```

- [ ] **Step 3: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py opc/layer2_organization/company_mode.py
git commit -m "feat: emit review_required event when work item enters AWAITING_HUMAN"
```

---

### Task 3.4: 前端 TaskDetailView 审核面板

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/workspace/TaskDetailView.tsx`
- Modify: `opc/plugins/office_ui/frontend_src/lib/wsClient.ts` — 添加 `sendReviewDecision`
- Modify: `opc/plugins/office_ui/frontend_src/types/kanban.ts` — 如需类型更新

**Interfaces:**
- Consumes: `task.phase`, `task.workItemId`, `task.reviewVerdict`, `onSend` callback
- Produces: `sendReviewDecision(workItemId, decision, feedback?)` WS 消息

- [ ] **Step 1: 在 wsClient.ts 中添加 sendReviewDecision 方法**

在 `VisualSocketClient` 类中，找到其他 `send` helper 方法附近添加：

```typescript
sendReviewDecision(workItemId: string, decision: 'approve' | 'reject' | 'rework', feedback?: string): void {
    this.send({ type: 'review_decision', work_item_id: workItemId, decision, feedback: feedback || undefined })
}
```

- [ ] **Step 2: 在 TaskDetailView.tsx 中添加审核面板**

在 `TaskDetailView` 组件的 `return` JSX 中，`task-detail-body` 之后、组件结尾之前，添加审核面板：

```tsx
{/* Review panel — shown when task is awaiting human review */}
{(task.phase === 'awaiting_human' || task.phase === 'awaiting_manager_review') && (
  <ReviewPanel task={task} onDecision={(decision, feedback) => {
    // Use onSend if available (checkpoint reply path), else direct WS
    if (onSend) {
      const label = decision === 'approve' ? '通过' : decision === 'reject' ? '驳回' : '返工'
      const content = feedback ? `${label}: ${feedback}` : label
      onSend(content, task.id)
    }
  }} />
)}
```

- [ ] **Step 3: 实现 ReviewPanel 内联组件**

在 TaskDetailView.tsx 文件中（组件定义之前或单独提取），添加：

```tsx
function ReviewPanel({ task, onDecision }: { task: KanbanTask; onDecision: (decision: string, feedback?: string) => void }) {
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState('')

  return (
    <div className="review-panel">
      <div className="review-panel-header">
        ⏳ 等待人工审核
        {task.workItemRoleName && <span className="review-role"> · {task.workItemRoleName}</span>}
      </div>

      {task.reviewVerdict && (
        <div className="review-feedback">
          上次反馈: {task.reviewVerdict}
        </div>
      )}

      <div className="review-actions">
        <button className="review-btn approve" onClick={() => onDecision('approve')}>
          ✓ 通过
        </button>
        <button className="review-btn reject" onClick={() => { setShowFeedback(true) }}>
          ✗ 驳回
        </button>
        <button className="review-btn rework" onClick={() => { setShowFeedback(true) }}>
          ↺ 返工
        </button>
      </div>

      {showFeedback && (
        <div className="review-feedback-input">
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="输入反馈理由..."
            rows={3}
          />
          <div className="review-feedback-actions">
            <button onClick={() => { onDecision('rework', feedback); setShowFeedback(false); setFeedback('') }}>
              确认返工
            </button>
            <button onClick={() => { onDecision('reject', feedback); setShowFeedback(false); setFeedback('') }}>
              确认驳回
            </button>
            <button className="cancel" onClick={() => { setShowFeedback(false); setFeedback('') }}>
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
```

在文件顶部添加 `useState` import（如果尚未导入）。

- [ ] **Step 4: 添加 review-panel CSS**

在 `workspace/workspace.css` 末尾添加：

```css
/* Review panel */
.review-panel {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.review-panel-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
}

.review-role {
  font-weight: 400;
  color: var(--text-dim);
}

.review-feedback {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 8px;
  padding: 6px 8px;
  background: var(--bg);
  border-radius: var(--radius-sm);
}

.review-actions {
  display: flex;
  gap: 8px;
}

.review-btn {
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  cursor: pointer;
  font-size: 12px;
  transition: all 150ms ease;
}

.review-btn.approve {
  color: var(--green);
  border-color: var(--green);
}

.review-btn.approve:hover {
  background: var(--green);
  color: #fff;
}

.review-btn.reject {
  color: var(--red);
  border-color: var(--red);
}

.review-btn.reject:hover {
  background: var(--red);
  color: #fff;
}

.review-btn.rework {
  color: var(--yellow);
  border-color: var(--yellow);
}

.review-btn.rework:hover {
  background: var(--yellow);
  color: #000;
}

.review-feedback-input {
  margin-top: 8px;
}

.review-feedback-input textarea {
  width: 100%;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
  resize: vertical;
}

.review-feedback-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.review-feedback-actions button {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
  cursor: pointer;
  font-size: 11px;
}

.review-feedback-actions button.cancel {
  color: var(--text-dim);
}
```

- [ ] **Step 5: TypeScript 验证**

Run: `cd opc/plugins/office_ui/frontend_src && npx tsc -b --noEmit 2>&1 | grep -E "TaskDetailView|wsClient" || echo "No type errors in changed files"`
Expected: 无类型错误

- [ ] **Step 6: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/workspace/TaskDetailView.tsx \
       opc/plugins/office_ui/frontend_src/workspace/workspace.css \
       opc/plugins/office_ui/frontend_src/lib/wsClient.ts
git commit -m "feat: add human review panel to TaskDetailView with approve/reject/rework actions"
```

---

### Task 3.5: KanbanCard 审核徽章区分

**Files:**
- Modify: `opc/plugins/office_ui/frontend_src/kanban/KanbanCard.tsx:7-21` (STATUS_BADGE)

**Interfaces:**
- Produces: `awaiting_human` 使用橙色 badge，区别于 `awaiting_manager_review` 的黄色

- [ ] **Step 1: 修改 STATUS_BADGE 颜色**

在 KanbanCard.tsx 的 `STATUS_BADGE` 对象中，找到 `awaiting_human` 条目（~L14），将颜色从 `#fbbf24`（黄色）改为 `#f97316`（橙色）：

```typescript
// 原: awaiting_human: { label: 'Human Review', color: '#fbbf24' },
awaiting_human: { label: '人工审核', color: '#f97316' },
```

- [ ] **Step 2: Commit**

```bash
git add opc/plugins/office_ui/frontend_src/kanban/KanbanCard.tsx
git commit -m "feat: distinguish awaiting_human badge with orange color and Chinese label"
```

---

## Issue 2：云主机执行路由

### Task 2.1: 在 ws_handler._run_task 中添加 VM 路由判断

**Files:**
- Modify: `opc/plugins/office_ui/ws_handler.py:4804-4919` (_run_task)

**Interfaces:**
- Consumes: `self.engine.worker_registry.is_connected(user_id)`, `self.engine.tenant_vm_service.get_status(user_id)`
- Produces: VM 就绪时走 `dispatch_run_task`，否则走现有本地路径

- [ ] **Step 1: 添加 VM 路由方法**

在 ws_handler.py 中添加辅助方法：

```python
async def _should_dispatch_to_vm(self, user_id: str) -> bool:
    """Check if task should be dispatched to a cloud VM instead of local execution."""
    registry = getattr(self.engine, 'worker_registry', None)
    vm_service = getattr(self.engine, 'tenant_vm_service', None)
    if not registry or not vm_service:
        return False
    if not registry.is_connected(user_id):
        return False
    try:
        vm_status = await vm_service.get_status(user_id)
        return vm_status.get('status') == 'ready'
    except Exception:
        return False

async def _dispatch_to_vm(
    self,
    user_id: str,
    task_id: str,
    cmd: list[str],
    workspace_path: str,
    env: dict[str, str] | None,
    timeout_seconds: float = 3600,
) -> 'WorkerTaskOutcome | None':
    """Dispatch task execution to a connected worker VM."""
    registry = self.engine.worker_registry
    message = {
        "type": "run_task",
        "task_id": task_id,
        "cmd": cmd,
        "workspace_path": workspace_path,
        "env": env or {},
    }

    async def on_progress(text: str) -> None:
        await self.broadcast({
            "type": "session_progress",
            "payload": {
                "task_id": task_id,
                "entry": {"type": "assistant", "text": text},
            },
        })

    return await registry.dispatch_run_task(
        user_id, task_id, message, on_progress, timeout_seconds
    )
```

- [ ] **Step 2: 在 _run_task 的执行路径中插入路由**

在 `_run_task` 方法中，找到实际调用 engine 执行任务的位置（~L4884 `response = await engine.process_message(...)` 之前），插入：

```python
# VM dispatch: try cloud execution first
user_id = data.get("user_id") or self._current_user_id
if user_id and await self._should_dispatch_to_vm(user_id):
    try:
        outcome = await self._dispatch_to_vm(
            user_id=user_id,
            task_id=task_id,
            cmd=task_cmd,  # 需要从上下文获取实际的 cmd 列表
            workspace_path=project_id,
            env=task_env,
        )
        if outcome is not None:
            # VM execution completed
            if outcome.returncode == 0:
                await self.broadcast({"type": "task_complete", "payload": {
                    "task_id": task_id, "status": "success",
                    "output": outcome.stdout[-5000:],
                }})
            else:
                await self.broadcast({"type": "task_complete", "payload": {
                    "task_id": task_id, "status": "error",
                    "error": outcome.stderr[-2000:] or outcome.stdout[-2000:],
                }})
            return  # VM handled it, skip local execution
        # outcome is None — timeout or disconnect, fall through to local
        logger.warning("VM dispatch returned None for task %s, falling back to local", task_id)
    except Exception:
        logger.warning("VM dispatch failed for task %s, falling back to local", task_id, exc_info=True)
```

注意：`task_cmd` 和 `task_env` 的具体变量名需要根据 `_run_task` 方法的实际实现确认。如果 cmd 是在 engine 内部构建的，可能需要将 VM dispatch 逻辑下沉到 engine 层。

- [ ] **Step 3: 运行测试**

Run: `cd /Users/laiweichao/Documents/OpenOPC-main && python -m pytest tests/ -q --tb=short 2>&1 | tail -20`
Expected: 无新增失败

- [ ] **Step 4: Commit**

```bash
git add opc/plugins/office_ui/ws_handler.py
git commit -m "feat: add VM dispatch routing in _run_task with local fallback"
```

---

### Task 2.2: Company Mode work-item 级别 VM 路由

**Files:**
- Modify: `opc/layer2_organization/company_mode.py:5095` 附近 (_run_work_item 的 agent 调用点)

**Interfaces:**
- Consumes: `self.engine.worker_registry` (通过 engine 引用)
- Produces: work-item 级别的 VM dispatch，与 Task 2.1 的路由逻辑一致

- [ ] **Step 1: 定位调用点**

在 `company_mode.py` 的 `_run_work_item` (L4988) 中，找到 agent adapter 调用点（~L5095-5101）：

```python
result = await asyncio.wait_for(
    (
        self.seat_executor.run_turn(task, member_session=member_session)
        if self.seat_executor is not None
        else self.execute_task(task)
    ),
    timeout=self.work_item_timeout,
)
```

- [ ] **Step 2: 在调用点之前插入 VM 路由检查**

```python
# VM dispatch check — try cloud execution before local
vm_dispatched = False
engine = getattr(self, '_engine', None) or getattr(self, 'engine', None)
if engine:
    registry = getattr(engine, 'worker_registry', None)
    vm_service = getattr(engine, 'tenant_vm_service', None)
    user_id = getattr(self, '_user_id', None)
    if registry and vm_service and user_id:
        try:
            vm_status = await vm_service.get_status(user_id)
            if vm_status.get('status') == 'ready' and registry.is_connected(user_id):
                # Build cmd for VM dispatch
                vm_message = {
                    "type": "run_task",
                    "task_id": task.id,
                    "cmd": task.cmd if hasattr(task, 'cmd') else [],
                    "workspace_path": self._project_id,
                    "env": {},
                }
                async def _on_progress(text: str) -> None:
                    if hasattr(self, '_emit_progress'):
                        await self._emit_progress(task.id, text)

                outcome = await registry.dispatch_run_task(
                    user_id, task.id, vm_message, _on_progress, self.work_item_timeout
                )
                if outcome is not None:
                    vm_dispatched = True
                    # Convert WorkerTaskOutcome to TaskResult
                    from opc.core.models import TaskResult
                    result = TaskResult(
                        success=outcome.returncode == 0,
                        output=outcome.stdout[-5000:],
                        error=outcome.stderr[-2000:] if outcome.returncode != 0 else "",
                    )
        except Exception:
            logger.warning("VM dispatch failed for work item %s, falling back to local", task.id, exc_info=True)

# Original local execution path (unchanged)
if not vm_dispatched:
    result = await asyncio.wait_for(
        (
            self.seat_executor.run_turn(task, member_session=member_session)
            if self.seat_executor is not None
            else self.execute_task(task)
        ),
        timeout=self.work_item_timeout,
    )
```

- [ ] **Step 3: 运行测试**

Run: `cd /Users/laiweichao/Documents/OpenOPC-main && python -m pytest tests/ -q --tb=short 2>&1 | tail -20`
Expected: 无新增失败

- [ ] **Step 4: Commit**

```bash
git add opc/layer2_organization/company_mode.py
git commit -m "feat: add VM dispatch routing in company_mode _run_work_item"
```

---

### Task 2.3: 端到端验证

**Files:**
- No file changes

- [ ] **Step 1: 启动 opc ui**

Run: `cd /Users/laiweichao/Documents/OpenOPC-main && python -m opc ui --rebuild 2>&1 | head -20 &`
Expected: Server starts on :8765

- [ ] **Step 2: 验证状态徽章**

打开浏览器访问 http://localhost:8765，确认：
- rail-top 有三个图标（信号/云/钥匙）替代原来的圆点
- 每个图标有颜色状态指示
- hover 显示 tooltip

- [ ] **Step 3: 验证审核面板**

在 Company Mode 下触发一个任务，确认：
- 当 work-item 进入审核状态时，TaskDetailView 显示审核面板
- 面板有通过/驳回/返工按钮
- 点击按钮发送正确的 WS 消息

- [ ] **Step 4: 验证 VM 路由**

确认当 VM 状态为 ready 且 worker 已连接时，任务被派发到 VM：
- 查看日志确认 dispatch 路径
- 确认 fallback 到本地执行正常工作
