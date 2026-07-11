# toC SaaS 化：每用户一台 SkyPilot 云主机作为执行沙箱

> 承接 `docs/saas-conversion-notes.md` 里的灵感记录。那份笔记里已经确认了一个阻塞项：当前代码库租户隔离等于零（agent 能读写工作区外任意文件，包括平台凭证目录）。本设计是 toC 方向的具体架构方案，用"每用户一台 SkyPilot 云主机"的 VM 级隔离来解决这个阻塞项。toB（私有化部署）是另一条独立轨道，本文档不展开，留待后续单独讨论。

## 背景与目标

OpenOPC 现状假设"单机单用户"。toC 要开放给不懂技术的用户用，核心诉求是：给每个用户一个隔离的执行环境，同时尽量少改动现有的 `layer3_agent`/`layer4_tools` 代码。

本设计范围：**仅 toC，仅 Claude Code adapter，服务规模是 <50 人内测**。toB、codex/cursor/opencode adapter、计费系统均在范围之外（见"范围边界"一节）。

## 架构总览

采用"控制面集中，云主机只当执行沙盒"的架构，而不是把整个 OpenOPC 引擎搬进每个用户的云主机：

```
用户浏览器
   │  (现有 WS，走 Office UI，不变)
   ▼
中心控制面（现有 OPCEngine + Office UI，本设计扩展）
   ├─ 账号库（新增：注册/登录，产出 user_id）
   ├─ Tenant VM 生命周期管理（新增：包一层 SkyPilot 调用）
   ├─ Worker 连接注册表（新增：谁的 VM 现在连着，token 是谁的）
   ├─ 用户凭证库（新增：加密存储每个用户自己填的网关 key）
   └─ layer2/layer3/layer4 原有调度逻辑（改造：exec/file_ops 目标从"本机"变成"某个已连接的 worker"）
        ▲
        │ (VM 主动发起的出站 WS 长连接，不开入站端口)
        │
SkyPilot 拉起的用户 VM（每用户一台，stop/start 复用磁盘，不是常驻算力）
   └─ `opc worker`（新增运行模式，复用现有 layer3_agent/adapters + layer4_tools 代码）
        └─ claude CLI 子进程（每条消息一个新进程，走 --resume/--continue 接上下文）
```

核心原则：**worker 不是新协议，是把 `opc/layer3_agent/adapters/*` 和 `opc/layer4_tools/*` 现有的本机子进程管理逻辑，原地搬进一个新的运行模式里，通过一条它自己发起的 WS 连接把调用面透传给中心控制面**。

## 为什么选"出站连接"而不是"入站 API"

对比过三种远程执行通道：

| 方案 | 做法 | 取舍 |
|---|---|---|
| SSH | 控制面直接 SSH 到 SkyPilot 集群跑命令/传文件 | 零新代码，但长会话进程管理（claude CLI 是常驻交互式子进程）、断连重连要在 SSH 层上自己补 |
| 自建守护进程 + 入站 API | VM 里跑 HTTP/gRPC 服务，控制面主动调用 | 协议贴合现有工具语义，但每台用户 VM 都要开入站端口——50 个用户等于 50 个新攻击面 |
| **自建守护进程 + 出站连接（采用）** | worker 启动后主动连回控制面 | 复用"agent 本来就需要出网"这条已有的网络策略，不新增入站暴露面；工程量与入站 API 方案相当，安全姿态更好 |

## 用户注册与登录（MVP）

现有代码调研确认：OpenOPC 目前完全没有人类用户账号/登录层——`chat_store.py`/`agent_store.py` 的表结构、`opc/core/config.py` 的路径解析都是"单机单隐式用户"设计，没有 `user_id` 概念，前端也没有任何登录路由。这是 toC 的前置缺口：本文档里"VM 归属""凭证库""活跃计时"等所有"按用户"的逻辑都需要一个稳定的 `user_id` 作为锚点，必须先有账号体系才能落地。

v1 采用最简机制，明确"先跑起来，后续再优化"：

- **注册**：填用户名 + 邀请码，邀请码校验通过即建号（新表 `users`：id、username、invite_code、created_at）。
- **登录**：填用户名 + 邀请码（邀请码本身就是登录凭证，不单独设密码），校验通过后发一个会话 token（cookie/localStorage），后续浏览器 WS 连接带上这个 token 做身份识别。
- **明确留到后续优化**：邀请码一次性/多次使用策略、密码找回、邮箱验证、OAuth/SSO、邀请码批量生成的管理界面。这些不阻塞 v1。

## 组件

- **账号库（新增）**：`users` 表 + 注册/登录路由，产出的 `user_id` 是本设计里其余所有新增组件的关联键。
- **`opc worker`（新增运行模式）**：跑在用户 VM 里，复用 `layer3_agent/adapters/claude_code.py` 和 `layer4_tools`（本轮范围：`shell_exec`、`file_ops`、`web_search`；不含 browser/Playwright）。启动后主动建立到控制面的出站 WS 连接并完成鉴权。
- **Tenant VM 生命周期管理（新增）**：包装 SkyPilot 调用（launch/stop/start），维护"用户 → 集群名/状态"的映射，自己记录用户最近活跃时间用于决定何时挂起（见下）。
- **Worker 连接注册表（新增）**：维护"哪个用户的 worker 现在连着、用的是哪个鉴权 token"，供调度逻辑判断任务能不能立即派发还是要先唤醒/拉起 VM。
- **用户凭证库（新增）**：按用户加密存储网关凭证（见"凭证模型"一节），应用级密钥加密，绝不明文落库/落日志。
- **现有 `layer2`/`layer3`/`layer4` 调度逻辑（改造）**：`shell_exec`/`file_ops`/agent 的 `start_process()` 的执行目标从"直接在本机跑"变成"经 worker 连接转发给已连接的那个用户的 VM 跑"。

## 数据流 / 生命周期

**首次发消息（新 chat，agent=claude_code）：**

```
用户发消息 → 控制面查"这个用户有没有 VM"
  ├─ 没有 → SkyPilot 冷启动（sky launch，跑 setup 装 claude CLI，1~3 分钟量级）
  ├─ 有但是 stopped → SkyPilot 唤醒（sky start，磁盘原样恢复，几十秒量级）
  └─ 有且 worker 已连上 → 直接派发，无延迟
       ↓
worker 连接建立（VM 内守护进程出站连上控制面，token 鉴权）
       ↓
控制面把这次调用参数发给 worker：用户消息 + 当前生效的凭证配置（key/base_url/model）+ resume_session_id（如果有）
       ↓
worker 复用现有 adapter 代码 spawn claude CLI 子进程（带 --resume/--continue）
       ↓
子进程 stdout 逐行产出 → worker 逐行转发回控制面（走 worker WS）
       ↓
控制面收到的行原样喂给现有 event_adapter → ws_handler → 浏览器 WS（这条链路不变）
       ↓
进程退出 → worker 把新的 resume_session_id 回传 → 控制面存进现有 session store（元数据留在中心，不下放到 VM）
```

**空闲挂起：**

控制面自己记录每个用户最近一次交互时间，超过阈值后主动调 `sky stop`（保留磁盘）。**不依赖 SkyPilot 自带的 `autostop`**——因为 `opc worker` 是一个常驻进程，从 SkyPilot 角度看这台机器"一直有进程在跑"，`autostop` 的空闲判定（基于 job/SSH 会话）对这种架构不生效。

**冷启动延迟**：首次开新 chat 可能要等 1~3 分钟（装 claude CLI 等）。<50 人内测规模下，v1 直接接受这个延迟，UI 给"环境准备中"的明确等待状态，不做预热池。

## 持久化：为什么本地磁盘不是可选项

调研现有代码确认：Claude Code 的多轮对话上下文续接，靠的是 CLI 自己读写在本机 `~/.claude/` 目录下的会话文件（`--resume`/`--continue`），**不是** OpenOPC 重新拼历史发过去（`opc/layer3_agent/adapters/claude_code.py` 的 `_build_session_args`，`opc/layer3_agent/external_broker.py` 的 resume 存取逻辑）。

这意味着：

- VM 本地磁盘持久化（stop 而不是 down）不只是省钱手段，而是**多轮对话能接上下文的功能性前提**——VM 被销毁重建，`~/.claude/` 没了，对话就断了。
- `~/.claude/`、用户 workspace、`.opc/` 内部状态三者必须绑在同一块磁盘上一起持久化。stop/start 天然满足（同一块盘）；如果以后做"长期不用就销毁+备份到桶、下次恢复"的兜底策略，备份/恢复必须是这三者的整体原子快照，不能只备份 workspace。
- 这也印证了"用云存储桶 FUSE 挂载做存储/计算分离"不适合这个 workload：CLI 频繁读写 `~/.claude/` 下的小文件/会话状态，FUSE 挂载桶（`MOUNT`/`MOUNT_CACHED`）在这类高频小文件场景下有已知隐患（rename 原子性、文件锁语义），v1 不采用，只用本地磁盘 + stop/start。

## 凭证模型

采用统一的"用户自填凭证"机制，官方与第三方网关在 OpenOPC 这一层是**同一套结构**，只是 UI 预设不同：

- 每次任务派发时，控制面按当前用户查出凭证配置（key、base_url、model），作为调用参数动态传给 worker——凭证从不烤进 VM 镜像或环境变量常驻，只在 spawn 那一刻注入子进程。这个机制本身在换模型/换网关时天然生效：用户在页面上改了配置，下一次任务直接用新配置，不需要重启或重新部署 VM。
- **官方预设**：base_url 锁定指向平台自己的模型聚合网关，用户只需要粘贴自己在该网关上注册到的 key。
- **自定义/第三方预设**：base_url 和 key 都由用户自己填（对接 Anthropic 官方或其他中转）。
- **限流问题结构性绕开，v1 不在 OpenOPC 侧写配额代码**：因为每个用户在网关上拿到的是自己独立配额的 key，用超了只影响自己，不影响其他用户。

**待确认依赖（不是本设计要建的东西）**：平台现有的模型聚合网关是否已经支持"用户自助注册 + 按 key 独立配额"？如果网关侧还没有这个能力，"官方预设"这条路径会从"纯前端加个输入框"变成"要先在网关侧补一个自助注册面"，工程量评估需要更新。

## 鉴权与隔离边界

- **worker↔控制面连接鉴权**：每台 VM 在 SkyPilot 拉起时发一个专属一次性 token（作为 `run:` 命令的环境变量注入，或开机后向控制面换取），worker 用它做 WS 握手鉴权。VM 销毁后 token 失效。
- **这个设计解决什么，不解决什么**：VM-per-user 隔离彻底解决了"能不能跨租户读到别人的 workspace/凭证文件"（toC 场景下一人一台机器，OS 级边界）。但**不解决**代码层面本身的问题——`opc/layer4_tools/file_ops.py` 对绝对路径零校验、`opc/layer4_tools/shell.py` 的 `shell_exec` 默认无沙箱——这些代码级漏洞依然原样存在，toC 的安全性来自 VM 边界这个外部结构，不是把代码修好了。这个方案只覆盖 toC；toB 是"一客户一部署"，本来没有多租户问题，但如果以后 toB 也要支持"一套部署给多个客户共享"，这些代码级问题需要单独修，不能假设这次设计顺带解决了。
- BYOK 模式下，"共享网关 token 泄露被盗刷"这类残留风险基本消解——泄露的是用户自己的 key，自己的账单，不牵连其他人。这个风险只在 `platform_gateway` 官方预设被大量使用、且网关侧配额机制不完善时才需要重新评估。

## v1 范围边界

**这轮要做：**
- 用户注册/登录（邀请码 + 用户名，MVP 级，产出 user_id 作为其余组件的锚点）
- SkyPilot 每用户一台 VM，launch/stop/start 生命周期，磁盘持久化
- 新增 `opc worker` 运行模式：复用 claude_code adapter（仅这一个）+ `shell_exec`/`file_ops`/`web_search`（不含 browser/Playwright）
- worker → 控制面出站 WS 连接，无入站端口；每台 VM 一次性 token 鉴权
- 统一的凭证预设模型（官方/自定义两种预设，同一套底层机制），加密存储，按次动态派发
- 空闲挂起由控制面自己记活跃时间、主动调 `sky stop`
- 冷启动接受 1~3 分钟延迟，UI 给"环境准备中"状态，不做预热池
- 输出流式管道复用现状，只是把数据源从"本机子进程"换成"worker 转发"

**这轮明确不做，记录留给后续：**
- 密码找回 / 邮箱验证 / OAuth/SSO / 邀请码批量管理界面——账号体系先跑最简版本，这些后续再补
- toB 私有化部署包——独立轨道，后续单独展开
- 计费/用量配额系统——独立轨道；这次靠"每人自己网关 key 自带配额"结构性绕开，前提依赖网关侧能力（见上）
- codex/cursor/opencode 在 VM 里跑——继续放着
- browser 工具（Playwright）在 VM 里跑——继续放着，会让镜像变重
- VM 预热池 / 自动扩缩容——规模上来再评估
- 长期闲置后销毁+备份到桶再恢复的兜底策略——只记为已知需要，这轮不细化机制
- claude CLI 二进制版本升级的镜像重建流程——记为持续运维成本，这轮不做自动化

## Open Questions

- 平台现有模型聚合网关是否已支持"用户自助注册 + 按 key 独立配额"？（决定"官方预设"这轮能不能真的可用）
- worker 断线重连的具体协议细节（任务执行中途 VM 网络抖动怎么处理，是否需要在控制面侧做任务级的幂等/重试）——本文档确认了"要有"，但重连时序/超时阈值等细节留给实施计划阶段。
- SkyPilot 的哪个云（AWS/GCP/其他）作为 v1 默认目标，是否已有账号/额度——未在本轮讨论中确认，需要在写实施计划前落实。
