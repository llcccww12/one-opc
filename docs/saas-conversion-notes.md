# SaaS 化改造 — 灵感记录（草稿，持续更新）

> 这是讨论过程中的灵感/决策记录，不是正式设计文档或实施计划。排期前还需要过一遍 `superpowers:writing-plans`。

## 背景

现状：OpenOPC 假设"单机单用户"，external agent（claude_code/codex/opencode/cursor）靠 `shutil.which` 找本机已登录的 CLI，模型/API Key 配置是纯 yaml 文件，没有 UI。

目标：开放给不懂技术的用户用（SaaS 化），核心诉求：
- 模型/Key 配置要能在页面上配（而不是改 yaml）
- 用户没装 codex/claude 等本地 CLI 时要有防呆，而不是运行到一半才报错
- 现在多了一层：把已有的模型聚合网关接进来，让 external agent CLI 直接走这个网关，而不是要求每个用户自己登录 claude/codex 账号

## ⚠️ 阻塞项（最高优先级）：租户隔离现状为零，必须先解决才能开放多租户

**结论（已核实，非猜测）：当前代码库没有任何机制阻止一个 agent 读写工作区外的文件——包括别的租户的 workspace，也包括平台自己存凭证的 `.opc/config/` 目录。"agent 只能在自己 workspace 里工作"目前只是约定，不是强制边界。**

证据：
- `opc/layer4_tools/file_ops.py` 的 `_resolve_task_path`：绝对路径**零校验**直接放行（`if candidate.is_absolute(): return candidate`）。
- `opc/layer4_tools/shell.py`：`shell_exec` 就是普通 `asyncio.create_subprocess_exec`，跟服务进程同一个 OS 用户，对整机文件系统有完整读权限。可选的 `bwrap`/`sandbox-exec` 沙箱**默认关闭**（`SandboxExecutionConfig.enabled=False`，`opc/core/config.py:619`），且开启后也**只限制写、不限制读**。
- `opc/layer2_organization/approval.py` 里唯一的路径权限检查：所有 `read_only=True` 的工具（`file_read`/`grep`/`glob`/`list_dir`）全部豁免检查；越界时默认是"弹出人工确认"而非硬拒绝。
- 外部 CLI（`claude`/`codex`）子进程同样继承宿主机完整文件系统权限，`--add-dir`/`--sandbox` 只是 CLI 自己内部权限引擎的提示，不是 OS 边界；且当前默认配置是 `full-auto`/`dangerously-bypass-approvals-and-sandbox`，等于把 CLI 自己那层权限引擎也关了。
- 全仓库搜不到任何 Docker/容器/chroot/seccomp/独立 OS 用户级别的隔离机制。

**影响**：这不只是"密钥会不会被偷"的问题——被 prompt injection 攻陷或恶意用户自己写的任务，理论上现在就能读到平台自己的主凭证文件、读到/写到别的租户的工作区内容。之前讨论的"网关 token 放哪、用不用代理层短效令牌"，都建立在"至少 agent 只能碰自己工作区"这个假设上，而这个假设目前不成立。**多租户方案（不管密钥怎么管理）在容器化隔离落地之前都不安全，这个必须排在模型/Agent 配置 UI 之前做。**

### 容器化隔离可行性评估

**结论：技术可行性高，是行业标准做法（E2B/Modal/Replit/Code Interpreter 等 agent 沙箱产品都是这个思路），不是探索性风险；但工程量不小，是本次改造里最大的一块。**

需要改的点：
- `opc/layer4_tools/shell.py`：`shell_exec` 从直接 `asyncio.create_subprocess_exec` 改成对目标容器做 `docker exec`（或类似接口），保持现有的 stdout/stderr/timeout 语义不变，改动面相对可控。
- `opc/layer3_agent/adapters/base.py`/`claude_code.py`/`codex_adapter.py`：`start_process()` 同理要改成在租户容器里拉起 `claude`/`codex`，意味着容器镜像里要预装这两个 CLI，且要跟进它们的版本更新——这是持续性运维成本，不是一次性工作。
- 新增容器生命周期管理：按 session/租户创建容器、只挂载该租户自己的 workspace 目录（不能挂 `.opc/config/`）、资源限额（防止一个租户把主机 CPU/内存吃满）、网络策略（agent 的 browser/web 工具需要出网，但不能碰到平台内部管理网络/数据库）、多机扩展时的调度（先单机 Docker 起步，规模大了再上 K8s）。
- `build_process_env` 现在是 `{**os.environ}` 全量继承宿主机环境变量，改造时必须换成显式 allowlist，否则即使加了容器，宿主机的环境变量也可能被整个透传进容器。

隔离强度可选梯度：
- **Docker（namespace+cgroup）**——起步够用，能挡住"意外/机会性"的越界读写和资源耗尽，但不是针对内核级容器逃逸的硬保证（此类漏洞存在但少见）。
- **gVisor (runsc)**——用户态内核拦截系统调用，隔离性更强，成本增加不大，Google Cloud Run/GKE Sandbox 用的就是这个，是不错的折中。
- **Firecracker microVM**——真正 VM 级隔离，最强，但要有 KVM 权限、不是随便一台 VPS 就能跑，运维复杂度显著上升，一般是专门做沙箱产品的公司才自建。

**一个值得考虑的捷径**：不一定要自己从零搭容器编排——市面上有专门做"agent 代码执行沙箱"的托管服务（同类型如 E2B），本质就是"给个 API，帮你起一个隔离好的沙箱环境，agent 在里面跑命令，用完销毁"。可以把 `shell_exec`/`file_ops` 的底层实现换成调用这类托管沙箱 API，用"按 session 付费+引入新的外部依赖"换取"不用自建容器编排/资源限额/多机调度"，能明显加快上线速度，值得和自建 Docker 方案一起比较成本再决定。

**注意**：容器化解决的是"agent 能不能越界读写文件系统"，不能替代之前讨论的"代理层+短效令牌"——即使容器里的 agent 被攻陷，它依然能读到注入进它自己进程环境变量里的凭证，所以两层防护要一起做，不是二选一。

## 已确定的范围决策

1. **v1 只做 Claude Code 的网关适配，Codex 先放一放。**
   原因：Claude Code 的自定义网关走的是纯环境变量（`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`/`ANTHROPIC_MODEL`/`ANTHROPIC_DEFAULT_*_MODEL`），可以直接在 spawn 子进程时注入；Codex 的 provider 配置是 `config.toml`（`model_providers.<name>` block + `env_key` 间接引用），需要额外做模板渲染，复杂度明显更高。先把 Claude Code 跑通，Codex 后续再评估。
2. **保留 `claude_code` + `native` 两种执行方式**，`codex`/`cursor`/`opencode` 先不管（不代表永久放弃，只是不在当前这轮范围内）。
3. **网关 token 是平台运营方级别的凭证，不是每用户 BYOK。** 这意味着不需要做一整套用户密钥托管，只需要一份全局网关配置（类似 `llm_config.yaml` 现有的 `api_key_env` 模式）。但也意味着必须在 OpenOPC 侧做限流/配额，否则一个重度用户能把网关额度刷爆，影响全平台。

## 代码调研发现的落点（供后续排期参考，不是任务清单）

- `opc/core/config.py:344` `ExternalAgentConfig` 目前只有 `model`/`model_flag`，没有 `base_url`/`auth_token(_env)`/`extra_env` 之类的字段，需要扩展 schema。
- `opc/layer3_agent/adapters/claude_code.py:192-199` `agent_home_env_vars()` 目前故意返回 `{}`（注释原话：不设置 `CLAUDE_CONFIG_DIR` 是为了让 Claude Code 复用宿主机已登录状态）。要改成：设置隔离的 `CLAUDE_CONFIG_DIR`，并把网关的 env block 通过 `extra_env` 注入子进程。
- Org UI（`RoleInspector.tsx`/`RoleTable.tsx`）目前只有 agent 工具选择下拉框，没有模型选择的配套 UI，也没有对应的 WS 请求类型（`docs/FRONTEND_BACKEND_MAP.md` 里目前没有 model/api_key 相关条目）。
- Agent 可用性检测后端已有雏形（`AdapterRegistry.initialize()` 会调 `is_available()`），但没暴露给前端，UI 防呆要靠这个数据源。

## 新增：SaaS 化的必要前提（独立轨道，不要和适配器改造混在一起排期）

- 用户体系（登录、租户隔离）—— 见上面"容器化隔离"，这不只是账号概念上的隔离，是文件系统/进程级别的硬隔离，当前完全缺失
- 计费/用量计量 —— 尤其因为网关 token 是平台共享的，这不是"锦上添花"而是"没有它会破产"级别的必要项
- 这两块工作量本身就很大，值得单独立项，不要默认塞进"模型配置 UI"这一轮改造里

## cc-switch 调研结论（已核实，仓库：github.com/farion1231/cc-switch）

**事实（repo 元数据 + README，115K+ star，MIT License）：**
- Tauri 2（Rust + TypeScript）**桌面应用**，Win/macOS/Linux 本机运行，数据存本机 `~/.cc-switch/cc-switch.db`（SQLite）——确认是客户端工具，不是服务端服务。
- 支持 7 个工具：Claude Code / Claude Desktop / Codex / Gemini CLI / OpenCode / OpenClaw / Hermes Agent。
- 核心功能：可视化管理/切换每个工具的 provider 配置，**50+ 预设**（AWS Bedrock、NVIDIA NIM、各类中转平台等）。
- 额外功能：本地反向代理 + 故障转移（format conversion / auto-failover / circuit breaker / health monitoring）；统一 MCP/Prompts/Skills 管理；**Usage & Cost Tracking**（花费/请求/token 趋势图 + 按模型自定义定价）；会话历史浏览。
- License 是 **MIT**，无 copyleft 顾虑，代码/数据可自由借用（保留版权声明即可）。
- 赞助方几乎全是 AI 网关转售商（20+ affiliate 链接）——是个人开发者的爆款工具，不是企业级基金会项目，长期维护节奏需自行判断。

**结论：不建议直接"内置"这个工具本身，但值得拆两块非代码资产来用：**

1. **不内置的原因**：Tauri/Rust 桌面单机架构，和 OpenOPC 纯 Python 服务端多租户的定位不匹配。真要塞进来，要么让 SaaS 用户在自己电脑装桌面 App（和"不懂技术的用户在网页上配置好"的目标自相矛盾），要么跨语言把 Rust 核心调进 Python 后端（PyO3/sidecar），集成成本远高于直接复用价值。
2. **值得白嫖的两块（MIT 协议下无风险）**：
   - **50+ provider 预设库**——直接抄它已经踩过坑的"每个工具对接每种网关分别要哪些 env/config 字段"这份知识，充到我们自己 `ExternalAgentConfig` 的预设列表里，省掉逐个调研的成本。抄数据/格式知识，不是抄代码依赖。
   - **Usage & Cost Tracking 面板的 UX 思路**（趋势图、按模型定价）可以参考着做，但底层数据源必须重写为服务端多租户版本（挂在 `layer6_observability` 现有 cost tracking 之上），它的实现是本机日志统计，不能直接搬。
3. 本地代理+故障转移这个功能概念上和我们想做的"网关注入"最接近，如果后续要支持多 provider 故障转移（不只是一个聚合网关），值得单独评估是否照此思路写服务端版本。

## Open Questions

- 网关配置到底是"平台全局一份" 还是"按角色/按项目可以配多份网关+多套模型别名"？(影响 schema 设计粒度)
- 限流/配额要做到多细：按用户？按项目？按角色？
- 要不要从 cc-switch 的预设库里挑哪些 provider 格式先搬过来（AWS Bedrock 优先，因为已经有真实配置样例）？
