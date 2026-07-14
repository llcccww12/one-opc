# 按用户 BYOK 模型凭证库（子项目 3）

## 背景

这是"toC SaaS 化：每用户一台 SkyPilot 云主机作为执行沙箱"整体计划的第三个子项目。子项目 2（`opc worker` 运行模式，`2026-07-14-opc-worker-runtime-mode-design.md`）已经定好了控制面向 worker 派发任务时需要的接口约定：

```python
async def get_credentials_for_user(user_id: str) -> tuple[str, str] | None:
    """返回 (api_key, api_base)；用户没配置过 BYOK 凭证时返回 None。"""
```

本文档实现这个接口的真实存储与前端配置入口。

## 范围澄清（重要，讨论中间澄清过一次）

这里的"凭证"指**用户自己的 Anthropic/Claude 模型 API Key**——填进设置面板后，会在派发任务给该用户的 worker 时被转发进去，让用户专属云主机里的 Claude Code CLI 能调得动模型。**与 SkyPilot/云主机基建访问凭证完全无关**——SkyPilot 用的是平台自己的 AWS 账号（管理员配置好的，用户不接触）。前端字段命名为"模型 API Key"，不用容易引起混淆的"云主机 Agent Key"这类措辞。

**v1 凭证获取方式：维持 BYOK**——用户自己去 Anthropic 官方（console.anthropic.com）或第三方中转渠道拿 key，产品本身不对接任何聚合网关。这对不懂技术的目标用户有门槛（需要境外支付方式或找靠谱的中转渠道），设置面板里会加一段静态说明文案 + 官方链接降低摸索成本，但**不做**平台自己对接网关这件事——如实记录为已知门槛，留给后续单独评估（"平台汇聚网关预设"这条路径本轮依然明确排除，取决于平台是否已有支持"用户自助注册+按 key 独立配额"的网关，属于未确认的外部依赖）。

## 目标

1. 每个用户能在设置面板里填自己的模型 API Key + Base URL，加密存储，只属于自己。
2. 子项目 2 派发任务前查询这个存储，拿到当前用户的 key；没配置过 → 派发前失败，报错引导去设置；换了 key → 下一次派发自动生效，不需要重启/重连 worker。
3. **只覆盖 worker/VM 路径**——现有全局 `LLMConfig`/`SettingsPanel`（服务 native agent）完全不动。调研确认 native agent 的 LLM 调用链路（`Task` 无 `user_id` 字段、`UserMessage.user_id` 硬编码 `"owner"`、`LLMProvider` 构造时焊死 config、`self.llm` 被 15 个文件 100 处引用）要改成按用户,是和这四个子项目加起来同量级的独立工程,本轮不动,如实记录为已知遗留范围。

## 非目标（本轮明确不做）

- native agent 改造（上面已说明,是完全独立的后续项）。
- 平台汇聚网关预设。
- key 有效性预检——不主动调 Anthropic API 验证 key 能不能用,留给 worker 实际执行时报错自然反馈。
- key 变更审计日志、多套 key/profile 切换——每用户当前只有一份生效的 key。

## 架构

新表 `user_credentials`（`ui_state.db`）：

```sql
CREATE TABLE IF NOT EXISTS user_credentials (
    user_id TEXT PRIMARY KEY,
    api_key_encrypted TEXT NOT NULL,
    api_base TEXT,
    updated_at REAL NOT NULL
)
```

`api_key` 用 **Fernet 对称加密**（`cryptography` 库,这轮补进 `pyproject.toml` 的 `dependencies`,之前不是显式依赖）落盘;`api_base` 明文（不算敏感信息,跟现有全局设置面板对 `api_base` 的处理方式一致）。

**应用级密钥**:`.opc/credential_key`,首次使用时自动生成（`Fernet.generate_key()`）,不存在就写一份并设文件权限为仅所有者可读写（`os.chmod(path, 0o600)`;Windows 上 `chmod` 是 no-op,可接受,不是本轮要解决的跨平台加固问题）。

新模块 `opc/plugins/office_ui/credential_vault.py`:

```python
class CredentialVault:
    def __init__(self, db: aiosqlite.Connection, key_path: Path) -> None: ...
    async def initialize(self) -> None: ...
    async def get_credentials(self, user_id: str) -> tuple[str, str] | None: ...
    async def set_credentials(self, user_id: str, api_key: str, api_base: str = "") -> None: ...
    async def has_credentials(self, user_id: str) -> bool: ...
```

**对接子项目 2**:之前约定的 `get_credentials_for_user` 可调用对象,实际是 `CredentialVault` 实例的 `get_credentials` **绑定方法**(依赖注入传给 `ExternalAgentBroker`,不是模块级裸函数/全局单例)。调用方视角签名一致(`async def (user_id: str) -> tuple[str, str] | None`),不违背子项目 2 已经写好的接口约定。

## 前端

身份菜单的设置面板新增一块独立区域,标题"模型 API Key"(不是"云主机 Agent Key"这类容易引起混淆的措辞),帮助文案:

> 这个 Key 会被转发给你专属云主机里运行的 Claude Code 使用,不会被其他用户看到或使用。可以在 [Anthropic 官网](https://console.anthropic.com/settings/keys) 申请,或使用第三方中转服务提供的 key + Base URL。

字段:API Key(密码框,留空 = 不覆盖已存的,跟现有全局设置面板交互习惯一致)、Base URL(文本框,可留空用官方默认地址)。走新 WS 类型 `get_vm_credentials`/`update_vm_credentials`,按当前连接的 `user_id` 读写,不需要额外鉴权(沿用 WS 本身已有的 `user_id` 绑定,即 `self._client_user_ids[ws]`)。

## 未配置/换 key 的行为(复述确认)

- **没填 key**:`get_credentials` 返回 `None` → 子项目 2 的 `_run_via_worker` 派发前失败,报错"请先配置你的模型 API Key"。
- **换 key**:下一次派发重新查一次 vault,自动生效,不需要重启/重连 worker——这是"每次派发时才查,不缓存"这个设计本身自带的效果,不需要额外的失效/通知机制。

## 测试计划

- `CredentialVault` 单测:加密往返(`set_credentials` 后 `get_credentials` 拿回同样的明文)、`has_credentials`、未配置返回 `None`、两个不同 `user_id` 互不可见。
- 密钥文件测试:首次调用自动生成 `.opc/credential_key`;文件已存在时复用,不重新生成(否则已加密的旧数据会解不开)。
- WS handler 测试:`get_vm_credentials`/`update_vm_credentials` 按 `user_id` 隔离(A 存的 key,B 查不到/B 查到的是 B 自己的,不是 A 的)。
- 端到端(结合子项目 2 一起验证,不能单独跑通,因为凭证要真的喂给 worker 才算验证完整):填一个真 key,发消息,确认 worker 收到的 `run_task` 消息里 `api_key` 字段是这个用户自己填的那个。

## Open Questions

- `.opc/credential_key` 这个应用级密钥本身怎么备份/迁移——如果这个文件丢了,所有用户存的 key 都解不开,需要重新填。这轮不做备份机制,记为已知运维风险,规模到需要多机部署控制面时需要重新设计(比如挪到环境变量或密钥管理服务)。
