# 每用户 SkyPilot 云主机：生命周期管理 + 绑定页（子项目 1）

## 背景

这是"toC SaaS 化：每用户一台 SkyPilot 云主机作为执行沙箱"（`2026-07-11-saas-toc-skypilot-design.md`）里描述的执行层的第一个可落地子项目。那份文档已经把整体架构设计完（控制面集中调度、VM 只做执行沙箱、出站 WS 连接、磁盘持久化续接对话），但完全没有代码落地。

账号系统（注册/登录/WS 鉴权）和登录后的租户数据隔离（项目/会话/看板不跨用户可见）已经上线（分别见 `2026-07-11-toc-account-system-plan.md`、`2026-07-11-post-login-ux-and-tenant-isolation-plan.md`），本轮建立在这两者之上。

**这一轮要解决的问题**：用户登录后，要能绑定一台专属于自己的 SkyPilot 云主机，云主机起来后预装好 Claude Code CLI，并验证装成功了。**不包括**任务执行、凭证隔离、数据回传——这些是后续子项目。

## 目标

1. 用户登录后进入一个"绑定云主机"页面，主动点击创建自己的 SkyPilot VM（显式步骤，不是无感自动触发）。
2. VM 起来后自动预装 Claude Code CLI（`npm install -g @anthropic-ai/claude-code`），并跑一次 `claude --version` 验证装成功。
3. 绑定成功（VM 状态 `ready`）之后才能进入 workspace；未绑定/绑定失败时卡在绑定页。
4. 一人一台，`user_id` 与 SkyPilot 集群名一一对应，记录持久化在 `ui_state.db`。

## 非目标（本轮明确不做，留给后续子项目）

- **`opc worker` 运行模式**：VM 上还不会跑任何 OpenOPC 任务，这轮只验证"CLI 装上了"，不验证"能不能真的执行 agent 任务"。
- **按用户凭证隔离（BYOK）**：Claude Code CLI 这轮不做鉴权登录，`claude --version` 不需要 API Key。用户自己的 Key 注入是下一个子项目的范围。
- **worker↔控制面出站 WS 连接、数据回传**：另一个子项目。
- **空闲自动挂起（`sky stop`）**：判定挂起需要"最近一次任务时间"，这轮 VM 上没有真实任务在跑，没有信号可用。这轮只有用户手动触发的生命周期操作。
- **多 agent（Codex/Cursor/OpenCode）**：这轮只装 Claude Code CLI 一个。
- **平台汇聚网关预设**：这轮及下一个凭证子项目都只做 BYOK。

## 架构

新增 **`TenantVmService`**——与现有只读的 `NodesService`（诊断面板，看本机*所有*集群）是两个不同职责的服务：`TenantVmService` 是用户操作面板，只关心"我自己的那一台"，且会做写操作（`sky launch`/`sky stop`/`sky start`）。

```
用户浏览器（BindNodePage，登录后 / 进 workspace 前）
   │  POST /api/vm/bind, GET /api/vm/status（纯 REST，Bearer token 鉴权）
   ▼
Office UI 服务端（新增 TenantVmService + TenantVmStore）
   │  asyncio.create_task 后台跑，不阻塞 HTTP 请求
   ▼
subprocess: sky launch <cluster_name> tenant_vm.yaml
   │  setup: 装 Node.js + npm install -g @anthropic-ai/claude-code
   ▼
subprocess: sky exec <cluster_name> "claude --version"
   │  验证成功 → status=ready；失败 → status=error + 记录 stderr
   ▼
TenantVmStore 落库（ui_state.db 的 tenant_vms 表）
```

## 数据模型

新表 `tenant_vms`，新增 `TenantVmStore`（独立文件，不再往 `UserStore` 里堆——`UserStore` 已经承载了账号+项目归属两块职责，VM 生命周期是第三块且会持续增长，值得单独一个 store，与 `AgentStore`/`ChatStore`/`UserStore` 平级）：

```sql
CREATE TABLE IF NOT EXISTS tenant_vms (
    user_id TEXT PRIMARY KEY,        -- 一人一台，主键即约束
    cluster_name TEXT NOT NULL,      -- opc-tenant-<user_id 前12位>
    status TEXT NOT NULL,            -- launching | ready | stopped | error
    auth_token TEXT,                 -- 为后续 opc worker 子项目预留字段，这轮生成但不消费
    error_message TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
```

`TenantVmStore` 接口：`get_vm(user_id) -> dict | None`、`create_vm(user_id, cluster_name, auth_token) -> None`、`update_status(user_id, status, error_message=None) -> None`。

## SkyPilot Task 定义

新文件 `opc/plugins/office_ui/skypilot/tenant_vm.yaml`：

```yaml
resources:
  cloud: aws
  cpus: 2+
  disk_size: 50

setup: |
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
  npm install -g @anthropic-ai/claude-code

run: |
  echo "tenant VM ready"
```

不锁具体机型/区域，让 SkyPilot 自选（AWS 已有账号/额度，见前置确认）。后续如果需要限定区域/机型，直接改这份 YAML，不涉及代码改动。

## REST API

延续 `auth_routes.py` 的模式（`LoginScreen` 所在的"登录后、进 workspace 前"这一层现状就是纯 REST，不复用 `VisualSocketClient`，不需要为了这一步把 socket 生命周期从 `App.tsx` 提出来）：

- `POST /api/vm/bind`（Header: `Authorization: Bearer <token>`）：
  - 无记录 → 生成 `cluster_name`/`auth_token`，落库 `status=launching`，`asyncio.create_task` 后台跑 launch+装 CLI+验证，立即返回 `{"ok": true, "status": "launching"}`。
  - 已有记录且 `status=launching` → 直接返回当前状态，不重复起任务（进程内维护一个 `user_id` 集合标记正在跑的任务，防止用户重复点击/多开页面并发触发两次 `sky launch`）。
  - 已有记录且 `status="error"` → 重新触发 `sky launch`（复用同一个 `cluster_name`，从头redo setup，因为上次可能没装完）。
  - 已有记录且 `status="stopped"` → 触发 `sky start`（复用磁盘，跳过 setup，比 `launch` 快）。
  - 已有记录且 `status="ready"` → 直接返回现状，不做任何操作。
- `GET /api/vm/status`（Header: `Authorization: Bearer <token>`）：返回 `{"status": ..., "cluster_name": ..., "error_message": ...}`，无记录时 `status="none"`。

两个路由都新增一个共享的 token 鉴权辅助函数（从 `Authorization: Bearer <token>` 头解析，调 `UserStore.get_user_id_for_token`），供 `auth_routes.py` 之外的路由复用。

## 前端

`Root.tsx` 从两态扩展为三态：

```
无 token          → LoginScreen
有 token，VM 未 ready → BindNodePage
VM ready          → App
```

新增 `auth/BindNodePage.tsx`：

- 挂载时调 `GET /api/vm/status`。
- `status="none"` 或 `"error"`：显示"创建云主机"按钮（`error` 态额外展示 `error_message`）；点击调 `POST /api/vm/bind`，转入 `launching` 展示。
- `status="launching"`：spinner + "环境准备中，预计 1~3 分钟"，每几秒轮询一次 `GET /api/vm/status`。
- `status="ready"`：显示"进入工作区"按钮，点击后 `Root` 切到 `App`。
- `status="stopped"`：显示"启动云主机"按钮（复用 `bind_vm` 走 `sky start` 分支——`TenantVmService.bind()` 内部按 `status` 分派到 launch 还是 start）。

## 失败场景

| 场景 | 处理 |
|---|---|
| 控制面没装 `sky` 二进制 | `error`，"未检测到 SkyPilot"（复用 `NodesService` 的 `shutil.which("sky")` 检查方式） |
| `sky launch` 失败（额度/权限/网络） | 存 `sky launch` 的 stderr 到 `error_message`，`status=error` |
| CLI 装好但 `claude --version` 跑不通 | 单独区分，`error_message` 前缀标注是验证阶段失败（不和 launch 失败的报错混在一起，方便用户/运维定位是"起不来"还是"起来了但装不上"） |
| 用户重复点击"创建云主机" | 进程内任务去重，不重复触发 `sky launch` |

## 测试计划

- `TenantVmStore`：单测覆盖 `create_vm`/`get_vm`/`update_status` 的读写往返（仿 `test_user_store.py`）。
- `TenantVmService`：mock `asyncio.create_subprocess_exec`（仿 `test_nodes_service.py`），覆盖：launch 成功+验证成功→`ready`；launch 失败→`error`；验证失败→`error`；`sky` 二进制缺失→`error`；重复 `bind` 不重复起任务。
- REST 路由：仿 `test_auth_routes.py`，覆盖鉴权失败（缺 token/token 无效）、`bind`/`status` 的正常路径。
- 前端 `BindNodePage`：仿 `LoginScreen.test.tsx` 的源码正则断言约定。
- 全部完成后走一次真实浏览器验证（需要真实 AWS 账号跑一次 `sky launch`，耗时数分钟）：登录 → 绑定页 → 点击创建 → 等待 ready → 进入 workspace；确认 VM 上 `claude --version` 确实可执行。

## 决定：超时

`sky launch`/`sky start`/`sky exec` 后台任务整体设 10 分钟超时（`asyncio.wait_for`）。超时视为 `error`，`error_message` 标注"操作超时"，不无限等待云侧异常。

## Open Questions

- VM 拉起后长期不用怎么处理（销毁 vs 一直计费）——本轮不做自动挂起，意味着用户绑定后如果不主动 `sky stop`，会一直计费。这轮先接受，运维层面需要有人工监控，下一个子项目（数据回传/任务执行）上线后自动挂起才有意义。
