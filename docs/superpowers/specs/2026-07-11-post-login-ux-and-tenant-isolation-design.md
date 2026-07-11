# 登录后体验优化 + 租户数据隔离 — 设计

## 背景

toC 账号系统（注册/登录/session token/WS 鉴权）已经上线（见 `2026-07-11-toc-account-system-plan.md`），但只做到"能不能连上 WS"这一层鉴权，登录后的产品体验和数据边界都还没跟上：

1. 登录后界面没有任何"我是谁"的存在感，Workspace 图标就是个纯导航按钮。
2. 没有任何地方能配模型/API Key，新建 chat 一问就报 `Missing Anthropic API Key`。
3. 已经决定走云主机方案（`2026-07-11-saas-toc-skypilot-design.md`），但那套完整架构（per-user VM、worker 出站连接、凭证按次注入）工程量很大，本轮不做，只需要一个能看见本机 SkyPilot 集群状态的入口。
4. **新发现（本轮实际验证确认，非推测）**：账号系统上线后，`WSHandler` 认证时解析出的 `user_id` 从未向下传递，项目列表/聊天记录/看板/agent 状态全部是全局共享，没有任何按用户过滤 —— 任意两个登录用户看到的是完全同一份数据。这是本轮优先级最高的项，属于安全/隐私缺陷，不是产品体验优化。

## 目标

- A. 登录后能看到自己的用户名，并有一个身份菜单入口。
- B. 能在页面上配置全局 LLM 模型/API Key，且配置后 Task Mode 的 native agent 和 external agent（claude_code CLI 子进程）都能实际用上，不用改 yaml、不用重启 `opc ui`。
- C. 新增只读的 "Nodes" 面板，展示本机 `sky status` 的集群状态。
- D. 修复项目/会话/看板的跨用户可见性问题：一个登录用户只能看到、只能操作自己拥有的项目及其下属数据。

## 非目标（本轮明确不做）

- 按角色/按项目的多套模型配置（现状 `LLMConfig` 全局唯一一份，改成多份是单独的大改造，Task Mode 本身也没有 role 概念）。
- SkyPilot per-user VM 生命周期管理、worker 出站连接、凭证按次注入（完整方案见另一份设计文档，本轮 Nodes 面板只读不操作）。
- Docker/gVisor/Firecracker 级别的进程/文件系统沙箱隔离（`saas-conversion-notes.md` 里讨论的代码执行沙箱，是比数据隔离更大的独立话题）。
- `agent_store.py`（Office 可视化的 agent/appearance 状态）的按用户隔离——现状完全没有 `project_id` 概念，是全局共享的装饰性可视化状态，跨用户串场景不属于本轮"数据不串"的范围，留作已知限制。
- 邀请码批量管理、密码找回等账号体系的后续优化（已在账号系统那份计划里明确排除）。

## D. 租户数据隔离（优先级最高）

### 现状证据

- `services/context.py:143` `list_project_entries()`：对 `.opc/projects/` 目录裸扫描，无 owner 概念。
- `services/project.py:82` `ProjectService.list()`：签名里没有 `user_id` 参数。
- `chat_store.py:418-441`：`channels`/`messages`/`task_progress` 表均无 `user_id`/`owner_id` 列。
- `services/session.py:499` `SessionService.list(self, *, project_id, limit)`：只按 `project_id` 过滤，不按用户。
- `services/kanban.py`：`KanbanService` 方法只接受 `project_id`/`task_id`，不涉及用户。
- `agent_store.py`：全文 grep `user_id` 零匹配，也没有 `project_id`。
- `ws_handler.py:1099` `_authenticate_ws_request` 解析出的 `user_id` 存进 `self._client_user_ids[ws]`（1119-1127），全文档只有 6 处引用，写入后从未被任何下游查询读取——认证和数据访问之间完全断层。

### 隔离边界：以 project 为锚点

Sessions/chat/kanban 已经天然挂在 `project_id` 下，只要在 project 这一层建立"谁能看见/操作哪个 project_id"的边界，其余数据结构不需要改 schema，只需要在入口处做归属校验。

### 数据结构变更

新表 `project_owners`（存入现有 `ui_state.db`，与 `agent_store`/`chat_store` 同库）：

```sql
CREATE TABLE IF NOT EXISTS project_owners (
    project_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    created_at REAL NOT NULL
)
```

### 行为变更

1. **创建项目时记录归属**：`ProjectService.create()` 成功创建项目后，插入一行 `(project_id, owner_user_id, now)`。`owner_user_id` 从调用方（WS handler）传入，来自 `self._client_user_ids[ws]`。
2. **列表按归属过滤**：`ProjectService.list()` 新增 `owner_user_id: str | None` 参数；非 `None` 时只返回该用户拥有的项目；`None`（匿名模式）时保持现状不过滤。
3. **集中访问控制**：新增 `ProjectService.assert_access(project_id, owner_user_id) -> None`，未命中时抛 `ServiceError`（权限错误码，如 `project_access_denied`）。所有携带 `project_id` 参数的 WS handler（session/chat/kanban/org 相关的 `_handle_*` 方法）在业务逻辑之前先调用这个检查——不能只在列表接口挡，否则用户能靠直接构造 `project_id` 绕过。
4. **WSHandler 打通**：每个 `_handle_*` 方法从 `self._client_user_ids[ws]` 取出 `user_id`，传给对应 service 方法。匿名模式（`user_store=None`，`user_id == "anonymous"`）下 `assert_access` 直接放行，不引入行为变化。
5. **历史数据迁移**：不写独立迁移脚本，改成幂等的启动时自愈逻辑——`ProjectService` 初次列出项目时，若某个 `project_id` 在磁盘上存在但在 `project_owners` 里没有记录，且 `users` 表里恰好只有一个用户，就把它补记为该用户所有；若 `users` 表有多个用户（多账号并存），未记录的历史项目暂不自动分配归属，对所有用户都不在列表中出现，需要时再手动指定（这轮不做手动指定 UI，先只覆盖"目前就一个账号"这个已知场景）。

### 已知限制（如实记录，不解决）

`agent_store.py` 的 Office 可视化状态（agent 外观、位置等）全局共享，不区分项目也不区分用户。多个用户同时打开 Office 页面会看到同一个虚拟办公室场景。这不泄露项目内容（会话/看板文本仍然被 D 的其余部分保护），但视觉上会串场景。留作后续需要时再评估。

## A. 用户身份菜单

- Rail `rail-bottom`（使用手册按钮上方）新增身份按钮：圆形头像（用户名首字母），点击弹出 popover，样式/交互模式参照 `org/OrgVersionSwitcher.tsx` 的"玻璃态弹出命令菜单"。
- 菜单内容：用户名（只读展示）、"模型 / API Key 设置"入口（打开 B 的设置面板）、"退出登录"（`clearSession()` + `window.location.reload()`）。
- 数据来源：`lib/auth.ts` 已有 `getStoredUsername()`，纯前端接线，无需新增后端接口。
- 匿名模式（未来如果关掉账号系统跑单机）下 `getStoredUsername()` 返回 `null` 时，直接不渲染这个身份按钮，行为保持原样。

## B. 全局模型 / API Key 设置

### 范围说明

现状 `LLMConfig`（`opc/core/config.py:267`）全局唯一一份，`OPCEngine` 配置加载路径固定读 `self.opc_home/config`，不区分 project/role。这轮维持"全局一份"，不做按角色/按项目的多套配置（那是独立的大改造，且 Task Mode 本身没有 role 概念，按角色配置对触发本轮 bug 的路径无效）。

### 后端

1. 新增 `opc/plugins/office_ui/services/settings.py`（仿 `services/org.py` 的 yaml 读写模式），提供：
   - `get_llm_config() -> dict`：读 `.opc/config/llm_config.yaml`，返回 `default_model`/`api_base`/`api_key`（脱敏，只回显是否已设置，不回显明文 key 原文，除非是刚保存的那一次响应）。
   - `update_llm_config(patch: dict) -> ServiceResult`：合并写回 yaml。
2. 新增 WS 请求类型 `get_llm_config` / `update_llm_config`，登记进 `docs/FRONTEND_BACKEND_MAP.md`。
3. **热更新**：`opc/engine.py:459-473` 的 `_runtime_config_signature_for` 目前只跟踪 `system_config.yaml`/`agent_config.yaml`/`company_corporate_config.yaml` 的 mtime，`llm_config.yaml` 不在其中，`_refresh_runtime_config_from_disk`（487-531）也从不把 `loaded.llm` 拷回 `self.config.llm`。这轮把 `llm_config.yaml` 加入签名跟踪范围，并在检测到变化时重建 `self.llm = LLMProvider(self.config.llm, ...)`。
4. **修复实际报错的根因**：`opc/layer3_agent/adapters/claude_code.py` 的 `agent_home_env_vars()`（192-199）目前恒返回 `{}`，子进程环境只继承 `os.environ`（第 98 行 `env = {**os.environ}`），从不注入配置里的 key。改成：读当前 `self.config.llm`，若 `api_key`/`api_base` 已配置，映射成 `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` 注入 `extra_env`，随子进程 spawn 一起生效。

### 前端

- 设置面板（由 A 的身份菜单打开）：模型名（文本框，对应 `default_model`）、API Key（密码框，仅在用户主动修改时才提交新值，留空/未改动不覆盖已存的）、Base URL（文本框，可留空用默认官方地址）。
- 保存成功后 toast 提示，无需刷新页面/重启服务。

## C. Nodes 面板（只读）

- Rail `rail-nav` 新增导航项 "Nodes"（英文命名，与 Workspace/Board/Office/Org 同级）。
- 后端新增 `opc/plugins/office_ui/services/nodes.py`：`asyncio.create_subprocess_exec("sky", "status", "-o", "json")`，解析 JSON 拿到集群名/状态（UP/INIT/STOPPED）/region/实例类型/单价/运行时长；`sky` 二进制不存在或调用失败时返回明确的"未检测到本机 SkyPilot" 状态，不是裸异常。
- 新增 WS 请求类型 `list_nodes`（前端手动点"刷新"按钮触发；不做后台自动轮询，避免每个已登录用户的浏览器都定时触发子进程调用）。
- 前端：卡片列表，状态色点（UP 绿 / INIT 黄 / STOPPED 灰 / 未检测到 灰底提示文案），只展示不提供启停操作按钮。

## 测试计划

- D：`ProjectService` 新增单测覆盖"用户 A 创建的项目不出现在用户 B 的列表里"、"用户 B 直接用用户 A 的 project_id 调用 session/chat/kanban 操作被拒绝"、"匿名模式不受影响"、"历史项目迁移到当前账号"。
- B：`services/settings.py` 单测覆盖读写 yaml 往返；`claude_code.py` 单测覆盖 `agent_home_env_vars()` 在配置了 key 时正确注入 `ANTHROPIC_API_KEY`。
- A/C：前端 `node:assert` 源码断言测试，参照现有 `auth.test.ts`/`LoginScreen.test.tsx` 的正则断言约定。
- 全部完成后走一次真实浏览器验证：两个不同账号分别登录，确认互相看不到对方的项目/会话；配置一个假 key 确认设置面板保存后 native agent 报错信息里带上了新 key（不需要真实调用成功，只需验证 key 确实被读取使用）。

## Open Questions

- `agent_store.py` 的 Office 可视化状态要不要按用户/项目隔离，留待后续单独评估（见"已知限制"）。
- 按角色/按项目的多套模型配置是否要做，留给下一轮单独立项（依赖是否真的有多角色差异化模型的需求）。
