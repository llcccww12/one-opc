# 设计文档：状态徽章重设计 + 审核面板 + 云主机执行路由

**日期**: 2026-07-15
**分支**: feature/tenant-skypilot-execution-layer

---

## 问题 1：状态徽章重设计

### 现状
`App.tsx` `.rail-top` 区域（logo "O" 旁边）有两个 `.conn-dot` 圆点（WS 连接状态 + VM 状态），设置区还有一个 LLM key 圆点。三个都是 10px 绿/黄/红圆点，仅靠 hover tooltip 区分，用户分不清。

### 方案
将三个 `.conn-dot` 替换为带图标的内联状态指示器：

| 状态 | 图标 | 颜色逻辑 | Tooltip 示例 |
|---|---|---|---|
| WS 连接 | `↕` 信号图标 (Lucide `Radio`) | connected=绿, connecting=黄(脉冲), error=红, off=灰 | `WS: connected — wss://...` |
| VM 就绪 | `☁` 云图标 (Lucide `Cloud`) | ready=绿, launching=黄(脉冲), stopped=灰, error=红, none=灰 | `云主机：就绪` / `准备中` / `已停止` / `出错 — msg` |
| LLM Key | `🔑` 钥匙图标 (Lucide `Key`) | 已配置=绿, 未配置=黄 | `LLM API Key: 已配置` / `未配置` |

**实现**：
- 新建 `frontend_src/components/StatusIcons.tsx`，内联 SVG（同 `SvgIcons.tsx` 风格，16×16，currentColor，stroke 1.5）
- `.rail-top` 布局：`O` logo 下方改为三行小图标堆叠，每行 `图标 + 颜色指示器`，用 CSS flex column，gap 6px
- `.conn-dot` CSS 保留但仅用于颜色逻辑，图标容器用新 class `.status-indicator`（带 hover 放大 + tooltip）
- LLM key 状态指示器从 App.tsx:2419 的 stat-chip 区域移出，整合进 `.rail-top` 的第三个位置
- 移动 LLM key 后，stat-chip 区域的 `conn-dot` 改为纯文字显示"API Key ✓"或"API Key ✗"

**涉及文件**：
- `App.tsx` — 重写 `.rail-top` JSX（~L2335-2339），移动 LLM key dot（~L2415-2421）
- `index.css` — 新增 `.status-indicator` 样式，调整 `.rail-top` gap
- 新建 `components/StatusIcons.tsx` — 三个图标组件

---

## 问题 2：云主机执行路由

### 现状
Company Mode 的任务执行链路（`ws_handler._run_task` → engine → `company_mode.py` / `native_agent.py` → `ClaudeCodeAdapter.start_process(cwd=local_workplace)`）完全不经过 SkyPilot 层。`WorkerConnectionRegistry` 和 `TenantVmService` 已实现但只用于文件浏览器，未接入主执行路径。

### 方案：执行路由拦截

在 `_run_task` 入口处插入路由判断：

```
_run_task()
  ├─ worker_registry.is_connected(user_id) AND vm_status == 'ready'
  │   └─ worker_registry.dispatch_run_task(...)   ← VM 执行
  └─ else
      └─ [现有本地执行路径不变]                     ← 本地 fallback
```

**关键设计决策**：

1. **路由点**：在 `ws_handler._run_task`（L4804）中，engine/project_id/session_id 解析完成后、实际调用 engine 执行前，插入 VM 路由判断。这样不改动 engine/company_mode 内部逻辑。

2. **VM 执行流程**：
   - 构建 `run_task` 消息（`{type: "run_task", task_id, cmd, env, workspace_path}`）
   - 调用 `worker_registry.dispatch_run_task(user_id, task_id, msg, on_progress, timeout)`
   - `on_progress` 回调转发到 WS 推送给前端（复用现有 `session_progress` 事件）
   - `WorkerTaskOutcome` 返回后，按 returncode 判断成功/失败，触发完成事件

3. **Fallback 策略**（任一条件触发则走本地）：
   - VM 未连接（worker 进程未启动或断开）
   - VM 状态非 `ready`（launching/stopped/error/none）
   - `dispatch_run_task` 返回 `None`（超时 3600s）
   - `dispatch_run_task` 抛异常

4. **Company Mode 特殊处理**：Company Mode 下一个 brief 会生成多个 work-item，每个 work-item 独立调度。路由判断应在每个 work-item 的执行调用点，而非 brief 级别。需要在 `company_mode.py` 的 work-item 执行路径（调用 agent adapter 之前）也加入同样的路由判断，或通过 engine 层统一抽象。

5. **Workspace 路径**：VM 执行时，workspace 路径由 VM 侧的 `WorkerRuntime` 自行解析（`_workspace_root / project_id`），控制平面只需传 `project_id`。本地执行时继续用 `get_project_workplace()`。

**涉及文件**：
- `ws_handler.py` — `_run_task` 方法加路由逻辑（~L4804）
- `company_mode.py` — work-item 执行路径加路由（需找到调用 agent adapter 的点）
- `worker_registry.py` — 无需改动，已有 `dispatch_run_task`
- `engine.py` — 可能需要暴露 `worker_registry` 引用给 ws_handler

---

## 问题 3：审核面板

### 现状
- Manager-review 循环中 `next_phase` 只会是 `APPROVED` 或 `READY_FOR_REWORK`，`AWAITING_HUMAN` 是死代码路径
- 5 轮 rework 后静默 auto-approve，无人工介入点
- 前端无审核 UI，Kanban 禁止手动拖拽
- 现有 escalation 机制（`EscalationEngine`）只用于工具权限审批，未接入 work-item 审核

### 方案：人工审核介入

#### Backend 改动

**A. 激活 `AWAITING_HUMAN` 路径**

在 `company_mode.py` 的 `_finalize_review_work_item`（~L7058）中，当 gate-harness 返回 `escalate` 或 manager-review 循环达到 stagnation cap 时，将 `next_phase` 设为 `AWAITING_HUMAN`（而非继续 AI review 或 auto-approve）：

```python
# 伪代码 — 在 _finalize_review_work_item 中
if gate_verdict == 'escalate' or rework_stagnation_detected:
    next_phase = Phase.AWAITING_HUMAN    # 激活人工路径
    # 调用 _save_review_rework_human_checkpoint 保存上下文
```

**B. 新增 WS 消息类型 `review_decision`**

在 `ws_handler.py` 中新增：
```python
async def _handle_review_decision(self, ws, data):
    """
    data: {
        "work_item_id": str,
        "decision": "approve" | "reject" | "rework",
        "feedback": str | None   # reject/rework 时可选
    }
    """
```
- 查找对应 work-item，校验其 phase 为 `AWAITING_HUMAN`
- `approve` → 设 phase 为 `APPROVED`，触发下游依赖项解锁
- `reject` → 设 phase 为 `FAILED`
- `rework` + feedback → 设 phase 为 `READY_FOR_REWORK`，将 feedback 注入 work-item context
- 推送 board 更新事件给所有 WS 客户端

**C. 推送审核请求事件**

当 work-item 进入 `AWAITING_HUMAN` 时，通过 `event_adapter` 推送：
```json
{"type": "review_required", "work_item_id": "...", "title": "...", "role": "...", "phase": "awaiting_human"}
```
前端收到后在 UI 上高亮提示。

#### Frontend 改动

**A. TaskDetailView 审核面板**

在 `TaskDetailView.tsx` 中，当 `task.phase === 'awaiting_human'` 时，在详情底部渲染审核面板：

```
┌─────────────────────────────────────┐
│ ⏳ 等待人工审核                       │
│ 角色: frontend-dev · 返工 2/5 次     │
│ 上次反馈: "CSS 类名冲突需修复"        │
│                                     │
│ [✓ 通过]  [✗ 驳回]  [↺ 返工+反馈]   │
│ ┌─────────────────────────────┐     │
│ │ 输入反馈理由...（返工/驳回时）│     │
│ └─────────────────────────────┘     │
└─────────────────────────────────────┘
```

- 通过按钮：发送 `{type: "review_decision", work_item_id, decision: "approve"}`
- 驳回按钮：展开输入框，确认后发送 `{decision: "reject", feedback}`
- 返工按钮：展开输入框，确认后发送 `{decision: "rework", feedback}`
- 操作完成后面板消失，显示结果 badge

**B. KanbanCard 审核徽章**

在 `KanbanCard.tsx` 的 `STATUS_BADGE` 中，`awaiting_human` 使用独立颜色（如橙色），区别于 `awaiting_manager_review`（黄色）。已有 `awaiting_human` 条目但颜色相同，改为橙色以区分人工审核。

**C. 全局审核通知**

收到 `review_required` WS push 时，在 App 层显示 toast 通知，点击后跳转到对应 kanban card。

**涉及文件**：
- `company_mode.py` — `_finalize_review_work_item` 激活 AWAITING_HUMAN（~L7058）
- `ws_handler.py` — 新增 `_handle_review_decision` + dispatch map 注册
- `event_adapter.py` — 新增 `review_required` 事件推送
- `TaskDetailView.tsx` — 审核面板组件
- `KanbanCard.tsx` — `awaiting_human` 颜色改为橙色
- `App.tsx` — toast 通知监听 `review_required`

---

## 实施顺序

1. **问题 1 (状态徽章)** — 纯前端，~1h，无后端依赖
2. **问题 3 (审核面板)** — 前后端联动，~3-4h，解决"卡审核"核心痛点
3. **问题 2 (云主机执行)** — 后端为主，~4-6h，需 VM 环境测试

## 风险

- **问题 2**：VM 侧 `WorkerRuntime` 的 `run_task` 消息格式需与控制平面构造的消息对齐，需确认 `cmd`、`env`、`workspace_path` 的传递契约
- **问题 3**：`AWAITING_HUMAN` 激活后如果人类长时间不响应，需有超时策略（建议：超时后自动 approve 并记录，与现有 auto_done_rework_cap 行为一致）
- **问题 1**：`.rail-top` 高度增加可能影响小屏幕下的 rail 布局，需测试
