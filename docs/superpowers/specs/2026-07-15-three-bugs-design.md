# 设计文档：状态徽章 + 审核面板 + 云主机执行

## 问题 1：状态徽章重设计

**现状**：`App.tsx` 的 `.rail-top` 里有 3 个 `.conn-dot`（10px 纯色圆点）代表 WS 连接 / VM 就绪 / LLM Key，视觉上完全不可区分。WS 和 VM 两个挤在 logo "O" 旁边，LLM Key 在另一个位置（settings 面板的 stat-chip 里）。

**方案**：将 3 个状态改为带图标的徽章，垂直排列在 logo 下方，每个徽章 = 图标 + 颜色状态点，hover 显示详细 tooltip。

### 布局设计

```
[rail-top]
  O         ← logo (不变)
  ⟳  WS    ← WS 连接图标 (16px)，颜色表示状态
  ☁  VM    ← 云主机图标 (16px)，颜色表示状态
  🔑 LLM   ← 钥匙图标 (16px)，颜色表示状态
```

每个徽章：
- 16×16 inline SVG 图标（复用 SvgIcons.tsx 内联方式）
- 右侧一个小圆点（8px，颜色同现有 ok/warn/error/off scheme）
- `title` 属性保持现有 tooltip 逻辑
- LLM Key 徽章从 settings 面板移到 rail-top，与 WS/VM 统一

### 图标选择

| 状态 | 图标 | 就绪 | 启动中/连接中 | 错误 | 未配置 |
|------|------|------|---------------|------|--------|
| WS 连接 | `Wifi` (信号图标) | 绿 | 黄 | 红 | 灰 |
| VM 云主机 | `Cloud` (云图标) | 绿 | 黄(脉冲) | 红 | 灰 |
| LLM Key | `Key` (钥匙图标) | 绿 | - | - | 黄 |

### CSS 变更

- 新增 `.status-badge` 容器样式（flex row, gap 4px, align-items center）
- 保留现有 `.conn-dot` 的颜色类（`.ok`, `.warn`, `.error`）复用到小圆点上
- `.rail-top` gap 从 8px 调整以容纳 3 行徽章
- 删除 `.conn-dot` 的 10px 圆点独立使用

### 涉及文件

- `frontend_src/App.tsx` — 移除 L2337-2338 的 conn-dot，新增 StatusBadge 组件引用；移除 L2419 的 LLM conn-dot
- `frontend_src/index.css` — 新增 `.status-badge` 样式，可保留 `.conn-dot` 颜色类供圆点复用
- 可选：新建 `frontend_src/components/StatusBadge.tsx` 或直接内联在 App.tsx

---

## 问题 2：人工审核面板

**现状**：
- `company_mode.py` 的 manager-review 循环 (`_finalize_review_work_item`) 里，`next_phase` 只设 `APPROVED` 或 `READY_FOR_REWORK`，从不设 `AWAITING_HUMAN`。
- 人工检查点代码 (`_save_review_rework_human_checkpoint`) 是死代码。
- 5 轮 rework 后静默自动通过（`auto_done_rework_cap`），无人工介入点。
- 前端无审核 UI，Kanban 禁止手动拖拽。
- 审核回复只能通过聊天自由文本推断（`_looks_like_escalation_reply`），无专用 WS 消息。

**方案**：在 backend 加一个专用的 `review_decision` WS 消息类型 + 在 `_finalize_review_work_item` 中正确设置 `AWAITING_HUMAN`；在 frontend 的 TaskDetailView 加一个审核面板。

### Backend 变更

#### B1. 新增 WS 消息类型 `review_decision`

`ws_handler.py` 新增 `_handle_review_decision(ws, data)`:
- 入参：`{ work_item_id: str, decision: 'approve' | 'reject' | 'rework', feedback?: str }`
- 逻辑：
  1. 从 engine 获取 work item，校验 phase 是否为 `AWAITING_MANAGER_REVIEW` 或 `AWAITING_HUMAN`
  2. `approve` → 设 phase 为 `APPROVED`，触发下游依赖项就绪
  3. `reject` → 设 phase 为 `FAILED`
  4. `rework` + feedback → 设 phase 为 `READY_FOR_REWORK`，写入 feedback
  5. 发 WS ack + 触发 board 更新推送

#### B2. 修改 `_finalize_review_work_item` 让审核能走到 `AWAITING_HUMAN`

在 `company_mode.py` 的 `_finalize_review_work_item`（~L7058）：
- 当 gate_harness 返回 `escalate` 时，不再继续 AI 审核循环，而是设 `next_phase = Phase.AWAITING_HUMAN` 并调用 `_save_review_rework_human_checkpoint`
- 保留 `auto_done_rework_cap` 作为最终安全网，但在 auto-approve 前先尝试 `AWAITING_HUMAN`（设一个超时，比如 10 分钟无人响应再 auto-approve）

#### B3. 推送审核请求到前端

当 work item 进入 `AWAITING_HUMAN`，通过 event_adapter 推送一个新的 event type：
- `review_required`：包含 `work_item_id`, `title`, `role_name`, `deliverables`, `review_feedback`

### Frontend 变更

#### F1. TaskDetailView 加审核面板

当 task 的 phase 为 `awaiting_human` 或 `awaiting_manager_review` 时，显示审核面板：
```
┌─────────────────────────────────┐
│ ⏳ 等待审核                      │
│ 角色: frontend-dev               │
│ 交付物: [...]                    │
│ 审核反馈: "代码质量需要改进..."    │
│                                  │
│ [✓ 通过]  [✗ 驳回]  [↺ 返工]     │
│ 反馈输入框 (选"返工"时展开)       │
└─────────────────────────────────┘
```

- 通过：发送 `review_decision` + `approve`
- 驳回：发送 `review_decision` + `reject`
- 返工：展开输入框，填写反馈后发送 `review_decision` + `rework` + feedback

#### F2. KanbanCard 加审核视觉提示

- phase 为 `awaiting_human` 的卡片显示一个醒目的审核 badge（区别于现有的黄色 "Mgr Review"，用橙色或红色脉冲）
- 点击卡片打开 TaskDetailView，审核面板自动展开

### 涉及文件

- `opc/plugins/office_ui/ws_handler.py` — 新增 `_handle_review_decision`
- `opc/layer2_organization/company_mode.py` — 修改 `_finalize_review_work_item` L7058 附近的 phase 判定
- `opc/plugins/office_ui/event_adapter.py` — 新增 `review_required` event 推送
- `frontend_src/workspace/TaskDetailView.tsx` — 新增审核面板
- `frontend_src/kanban/KanbanCard.tsx` — 新增 awaiting_human 视觉 badge
- `frontend_src/types/kanban.ts` — 如需新增类型定义

---

## 问题 3：云主机执行路径接入

**现状**：
- `TenantVmService`（VM 生命周期）+ `WorkerConnectionRegistry`（worker WS 连接管理）+ `WorkerRuntime`（VM 侧执行器）三个组件已实现。
- 但任务执行链路 `engine.py → company_mode.py/native_agent.py → ClaudeCodeAdapter.start_process()` 完全不经过这些组件。
- 执行永远通过 `get_project_workplace()` → 本地 `ClaudeCodeAdapter.start_process(cwd=workspace_path)` 在控制平面进程内跑。
- `worker_registry.dispatch_run_task()` 已实现但只被文件浏览器功能使用，从未被任务执行调用。

**方案**：在任务执行入口处加一个分支：VM ready 且 worker 已连接 → 派发到 VM；否则 → 本地执行（现有路径）。

### 执行路径改造

#### E1. 在 `ws_handler.py` 的 `_run_task` 中加 VM 分支

在 `_run_task`（~L4804）解析完 engine/project_id/task 后，插入：

```python
# 尝试 VM 派发
if self._should_dispatch_to_vm(user_id):
    outcome = await self._dispatch_to_vm(user_id, task, ...)
    if outcome is not None:
        return  # VM 执行成功
    # VM 派发失败，降级到本地
    logger.warning("VM dispatch failed, falling back to local execution")
```

#### E2. 新增 `_should_dispatch_to_vm` 方法

```python
def _should_dispatch_to_vm(self, user_id: str) -> bool:
    registry = self._engine.worker_registry
    vm_service = self._engine.tenant_vm_service
    if not registry or not vm_service:
        return False
    if not registry.is_connected(user_id):
        return False
    # 同步检查 VM 状态（或缓存最近一次状态）
    vm_status = asyncio.get_event_loop().run_until_complete(vm_service.get_status(user_id))
    return vm_status.get('status') == 'ready'
```

注：`get_status` 内部有 liveness check 频率限制（30s），不会每次调用都跑 `sky status`。

#### E3. 新增 `_dispatch_to_vm` 方法

```python
async def _dispatch_to_vm(self, user_id: str, task, ...) -> WorkerTaskOutcome | None:
    registry = self._engine.worker_registry
    message = {
        "type": "run_task",
        "task_id": task.id,
        "cmd": [...],  # 同 ClaudeCodeAdapter 的 cmd 构建逻辑
        "workspace_path": project_id,  # VM 侧用 WorkerRuntime._workspace_root / project_id
        "env": {...},
    }
    async def on_progress(text: str):
        # 转发到 UI（复用现有 session_progress 推送路径）
        await self._push_progress(task.id, text)

    outcome = await registry.dispatch_run_task(
        user_id, task.id, message, on_progress, timeout_seconds=3600
    )
    return outcome
```

#### E4. Company Mode 的 work-item 执行也走同一分支

`company_mode.py` 中执行 work item 的地方调用的是 `engine` 的 agent 执行路径。需要确保 engine 的执行路径也检查 VM dispatch。具体方式：
- `engine.py` 的执行方法（如 `run_task`）中加同样的 VM 分支检查
- 或者在 `company_mode.py` 的 work item dispatch 层面加分支

#### E5. 进度流转发

`WorkerRuntime`（VM 侧）已通过 WS 发送 `progress` 和 `task_complete` 消息。`WorkerConnectionRegistry.handle_worker_message` 已实现路由。需要确保 `on_progress` 回调正确转发到 UI 的 session_progress event：

- `worker_registry.dispatch_run_task` 的 `on_progress` 参数已支持
- 需要在 `_dispatch_to_vm` 中构造正确的 `on_progress` 闭包，调用 event_adapter 的进度推送

#### E6. 降级行为

| 场景 | 行为 |
|------|------|
| VM 未创建 (status=none) | 本地执行 |
| VM 启动中 (status=launching) | 本地执行（不阻塞） |
| VM 就绪但 worker 未连接 | 本地执行 + warning 日志 |
| VM 派发超时 | 本地执行 + warning 日志 |
| VM 派发返回错误 | 本地执行 + warning 日志 |

所有降级都是静默的，用户无感知（除非看日志）。VM ready 时自动切换到 VM 执行。

### 涉及文件

- `opc/plugins/office_ui/ws_handler.py` — 修改 `_run_task`，新增 `_should_dispatch_to_vm`, `_dispatch_to_vm`
- `opc/engine.py` — 确保 `worker_registry` 和 `tenant_vm_service` 在 engine 上可访问
- `opc/layer2_organization/company_mode.py` — work item 执行路径加 VM 分支（如果不在 engine 层统一处理）
- `opc/layer3_agent/worker_registry.py` — 无需修改，已有完整 API
- `opc/layer3_agent/worker_runtime.py` — 无需修改，VM 侧已实现

---

## 实施顺序

1. **问题 1 (状态徽章)** — 纯前端，独立，先做。预计 1-2 小时。
2. **问题 3 (审核面板)** — 前后端联动，核心功能。预计 3-4 小时。
3. **问题 2 (云主机执行)** — 后端改造，依赖审核功能稳定后再做。预计 4-5 小时。
