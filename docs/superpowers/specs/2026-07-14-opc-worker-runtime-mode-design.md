# `opc worker` 运行模式：worker↔控制面 relay（子项目 2）

## 背景

这是"toC SaaS 化：每用户一台 SkyPilot 云主机作为执行沙箱"整体计划的第二个子项目。子项目 1（VM 生命周期 + 绑定页 + 预装 Claude Code CLI，`2026-07-12-tenant-vm-lifecycle-binding-design.md`）解决了"用户有没有一台自己的、装好 CLI 的 VM"；这一轮解决"任务怎么真正跑到那台 VM 上"。

子项目 1 目前正在另一条实施线上落地，本文档不改动子项目 1 的范围，只在"依赖"一节说明后续会对它产出的文件（`tenant_vm.yaml`）追加一次改动。

## 目标

1. 新增 `opc worker` CLI 运行模式：跑在用户的 SkyPilot VM 上，主动建立到控制面的出站 WS 连接，用子项目 1 已经生成的 `auth_token` 鉴权。
2. 控制面判定"这个任务该用 claude_code 外部 agent 且 owner 有已连接的 worker"时，把任务转发给对应的 worker 执行，而不是在控制面本机跑子进程。
3. worker 本地复用现有 `layer3_agent` 的 adapter 代码真实 spawn `claude` CLI 子进程，文件读写、claude 自带的工具调用天然发生在 VM 本地，不做文件同步。
4. 支持多轮对话：连续两条消息能通过 `--resume` 接上下文（VM 磁盘持久化 + 控制面照常记录 resume_session_id 映射,两层职责不变）。
5. worker 没连接时，任务派发失败并给出明确报错——**不回退到控制面本机执行**（回退等于让"每用户隔离沙箱"这个核心目标失效）。

## 非目标（本轮明确不做）

- **文件同步机制**：VM 本地 workspace（`~/opc_workspace/<project_id>/`）内容完全由 worker 在本地产生，不假设控制面有历史文件要推送过去。这是已知限制，如实记录，不是这轮要解决的。
- **真实凭证库实现**：`run_task` 消息需要 `api_key`/`api_base`，这轮只定接口签名（见"交叉依赖"），真实的按用户存取是子项目 3 的范围。
- **多 agent**：只做 claude_code 一个（延续子项目 1 的范围决定）。
- **任务执行中途断线的恢复/续跑**：断线 = 这次任务失败，用户重新发消息，下一次靠 `--resume` 接上下文（不丢对话历史，只丢没跑完的这一次响应）。
- **worker 侧多任务并发排队**：假设一个 VM 一次只处理一个任务，与现状单会话串行的假设一致,不是新增限制。
- **空闲自动挂起**：这轮任务执行是真实的活跃信号了，但把它接到子项目 1 的"待办"挂起逻辑上，算作后续单独一次小改动，不在本轮任务列表里。

## 架构总览

```
控制面（现有 ExternalAgentBroker._run_monitored_process）
   │ 决定"这个任务该走 claude_code 外部 agent"之后，新增一层判断：
   │ 这个任务的 owner_user_id 有没有连着的 worker？
   │   有 → 走新的 _run_via_worker() relay 路径（本子项目新增）
   │   没有 → 抛错，报"云主机未连接"，不回退本机跑
   ▼
新增 /worker/ws 端点（与浏览器用的 /ws 分开，鉴权用 tenant_vms.auth_token，
不是用户 session token）
   │ 出站连接（VM 主动连回来，不开入站端口，与子项目 1 之前的整体
   │ 设计原则一致）
   ▼
opc worker（新增 CLI 命令，跑在 VM 上）
   │ 收到 run_task 消息后，本地实例化 ClaudeCodeAdapter，调用
   │ 从 external_broker.py 里抽出来的 run_adapter_process()（本机
   │ 路径和 worker 路径共用同一份 spawn+streaming 逻辑）
   │ 文件读写、claude 自带的 shell/文件工具，全部在 VM 本地发生
   ▼
逐行把 progress 文本回传给控制面 → 控制面原样喂给现有
event_adapter → ws_handler → 浏览器（这条链路完全不改）
```

## 前置重构：`process_runner.py`

现状调研确认：`ExternalAgentBroker._run_monitored_process`（`opc/layer3_agent/external_broker.py:577-1268`）把"spawn 子进程 + 逐行读 stdout/stderr + 检测 runtime failure + 提取 resume_session_id"的逻辑和 broker 自身的任务生命周期状态（store/approval_engine/task_preparer/communication）耦合在一起。这轮把可复用的部分抽成独立函数：

新文件 `opc/layer3_agent/process_runner.py`：

```python
async def run_adapter_process(
    adapter: ExternalAgentAdapter,
    cmd: list[str],
    workspace_path: str,
    extra_env: dict[str, str] | None,
    on_line: Callable[[str, str], Awaitable[None]],  # (stream_name, text) -> None
) -> ProcessResult:
    ...

@dataclass
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    resume_session_id: str | None
```

本机路径（`ExternalAgentBroker._run_monitored_process`）改为调用这个函数，行为不变（纯重构）。worker 路径同样调用它，只是 `on_line` 回调把每行文本包成 WS 消息发回控制面，而不是走本机的 `on_progress` 回调。

## Worker 侧组件

- **`opc worker start`**（新增 CLI 命令）：读环境变量 `OPC_CONTROL_PLANE_URL`/`OPC_WORKER_TOKEN`（VM 起来时由 SkyPilot task 注入，是"worker 怎么找到控制面、证明自己是哪台 VM"这两件基建层的事，跟用户填的模型 Key 无关，起来后不变）。建立到 `<OPC_CONTROL_PLANE_URL>/worker/ws?token=<OPC_WORKER_TOKEN>` 的出站连接，断线固定间隔重连（不做指数退避）。
- **`WorkerRuntime`**（新类，worker 进程主循环）：
  - 收到 `run_task` 消息 → 用消息里的 `resume_session_id` 构造 `ClaudeCodeAdapter` 实例（`session_mode="resume"` 若有 id，否则默认）→ 用消息里的 `api_key`/`api_base` 构造 `extra_env`（映射到 `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL`，与现有 `_apply_llm_config_env` 的映射方式一致）→ 调 `run_adapter_process`，`on_line` 回调把每行包成 `progress` 消息发回。
  - 结束后把 `ProcessResult` 包成 `task_complete` 消息发回。
  - 收到 `cancel_task` 消息 → 调 `adapter.cancel(task_id)`（复用现有方法，`ClaudeCodeAdapter.cancel` 就是 `self._process.kill()`）。
- **worker 侧项目 workspace**：VM 本地维护 `~/opc_workspace/<project_id>/`，`run_task` 消息带 `project_id`，worker 首次收到某个 `project_id` 时本地 `mkdir -p` 建好。

## 控制面侧组件

- **`WorkerConnectionRegistry`**（新类，纯内存态 `dict[user_id, aiohttp.web.WebSocketResponse]`）：随控制面进程重启清空，worker 断线重连即可重新注册，不持久化。
- **新增 `/worker/ws` 端点**：鉴权通过 `TenantVmStore` 新增方法 `get_user_id_for_auth_token(token: str) -> str | None`（反查——`tenant_vms.auth_token` 在子项目 1 里生成但没被消费，这轮开始消费）。
- **`ExternalAgentBroker._run_monitored_process` 改动**：顶部加分支——查 `task` 所属 project 的 `owner_user_id`（复用已完成的 `project_owners` 机制），若 `WorkerConnectionRegistry` 里有对应连接 → 调新方法 `_run_via_worker(...)`；没有 → 抛 `ServiceError("worker_not_connected", "云主机未连接，请检查绑定状态")`，中止派发。
- **`_run_via_worker(...)`**：先调 `get_credentials_for_user(owner_user_id)`（见下）；返回 `None` 时不发消息给 worker，直接失败，报"请先配置你的 API Key"；有值时把 `run_task` 消息发给对应连接，等待该 `task_id` 对应的 `progress`/`task_complete` 消息（用 `task_id` 做多路复用的 key，一个 worker 连接上同一时刻理论上只有一个任务，但用 `task_id` 索引更稳妥,不依赖"同时只有一个"这个假设）。

## 协议消息（worker ↔ 控制面，JSON over WS）

| 方向 | type | 字段 |
|---|---|---|
| worker→控制面 | `hello` | `cluster_name` |
| 控制面→worker | `run_task` | `task_id`, `project_id`, `message`, `resume_session_id`(可空), `api_key`, `api_base`(可空) |
| worker→控制面 | `progress` | `task_id`, `stream`("stdout"/"stderr"), `text` |
| worker→控制面 | `task_complete` | `task_id`, `returncode`, `resume_session_id`(可空), `stdout`, `stderr` |
| 控制面→worker | `cancel_task` | `task_id` |

## 交叉依赖

- **子项目 1**（正在另一条实施线落地，不阻塞它，本轮落地时追加一次改动）：`tenant_vm.yaml` 的 `setup:` 段除了装 Claude Code CLI，还要装 OpenOPC 本身（worker 要 `import opc.layer3_agent.adapters`）；`run:` 段从"起来就完事"改成启动 `opc worker start`；同时需要在 `envs:` 里声明 `OPC_CONTROL_PLANE_URL`/`OPC_WORKER_TOKEN`（`sky launch -e KEY=VALUE` 在 launch 时注入实际值，`OPC_WORKER_TOKEN` 用子项目 1 已生成的 `tenant_vms.auth_token`）。
- **子项目 3**（凭证库）：接口签名现在定下来——

  ```python
  async def get_credentials_for_user(user_id: str) -> tuple[str, str] | None:
      """返回 (api_key, api_base)；用户没配置过 BYOK 凭证时返回 None。"""
  ```

  本轮 `_run_via_worker` 只依赖这个函数签名，落在哪个模块（`opc/plugins/office_ui/credential_vault.py`，子项目 3 的产物）由子项目 3 定。子项目 3 落地前，本轮自己的端到端验证可以用一个返回固定测试 key 的 stub 函数代替，接口对齐后直接换成真实实现，不需要改调用方代码。
- **已完成的 `project_owners` 机制**：判断某个 task 该转发给哪个用户的 worker，靠 task 所属 project 的 owner_user_id。

## 范围边界

**这轮做**：`process_runner.py` 重构（纯重构，本机/worker 共用）；`opc worker start` CLI + `WorkerRuntime`；`/worker/ws` 端点 + `WorkerConnectionRegistry` + `auth_token` 反查鉴权；`ExternalAgentBroker` 新分支（有连接→relay，无连接→报错，不回退本机执行）；4 种协议消息；worker 断线固定间隔自动重连；`cancel_task` 生效（worker 收到后杀掉本地子进程）。

**这轮不做**：文件同步、真实凭证库实现、多 agent、执行中途断线恢复/续跑、worker 侧多任务并发排队、空闲自动挂起接入。

## 测试计划

- `process_runner.py` 抽出来后，跑现有 `external_broker` 相关测试全套回归，确认纯重构没改变行为。
- `/worker/ws` 鉴权：mock 连接，测 token 有效/无效/VM 不存在三种情况。
- `ExternalAgentBroker` 分支逻辑：mock `WorkerConnectionRegistry`，测"有连接→走 relay 路径"、"无连接→抛错且没调本机 `adapter.start_process`"、"有连接但凭证库返回 None →不发消息给 worker，直接报错"。
- `WorkerRuntime`：mock WS 收发，测收到 `run_task` 后正确调 `run_adapter_process`，`progress`/`task_complete` 消息内容正确；收到 `cancel_task` 后正确调 `adapter.cancel`。
- 端到端（复用子项目 1 已经跑起来的那台 VM，套一个 stub 凭证函数）：连续发两条消息，人工确认第二条真的接上了第一条的上下文（`--resume` 生效）——这轮唯一要求的"多轮"验证点。

## Open Questions

- worker 断线重连后，控制面侧 `WorkerConnectionRegistry` 是否需要区分"同一台 VM 的新连接"和"另一台 VM 冒充"——这轮鉴权靠 `auth_token` 本身的保密性，没做额外的连接指纹校验，记为已知的简化，非本轮阻塞项。
- `run_task` 消息里直接带 `api_key` 明文过 WS——这条连接是控制面主动信任的出站连接（TLS 加密传输,协议层没有额外加密要求),但落盘日志（如果 worker/控制面对这条连接做了调试日志）要注意别把 `run_task`/`progress` 整个消息体明文打进日志文件，这个注意事项写进实施计划里,不是这轮设计要解决的架构问题。
