# VM 工作区远程文件浏览器（子项目 4）

## 背景

这是"toC SaaS 化：每用户一台 SkyPilot 云主机作为执行沙箱"整体计划的第四个子项目,也是最后一个。前三个子项目分别解决了"有没有自己的 VM"（子项目 1）、"任务怎么真的跑到 VM 上、聊天内容怎么流回浏览器"（子项目 2）、"模型 Key 怎么按用户隔离"（子项目 3）。

讨论过程中确认:聊天文本的回传链路子项目 2 已经设计完（worker → `progress` 消息 → 控制面 → 现有 `event_adapter`/`ws_handler` → 浏览器,完全复用现状）,UI 隔离更早一轮就做完了。这一轮真正要补的缺口是:**agent 在 VM 上生成的文件/产出物**,现状"附件下载"（`attachment_store.py`）假设文件在控制面本机磁盘上,VM 上生成的文件控制面读不到,用户下载不了。本轮做一个远程文件浏览器:列目录、下载、删除。

## 目标

1. 浏览器里新增"文件"面板,树状展示用户自己那台 VM 上 `~/opc_workspace/<project_id>/` 目录的内容。
2. 支持下载单个文件、删除文件/文件夹。
3. 所有操作复用子项目 2 已经搭好的 worker↔控制面出站 WS 连接,不新开一条连接。

## 非目标（本轮明确不做）

- **在线编辑/写回 VM**:只读+删除+下载,不做"改完存回去"。
- **从浏览器上传文件到 VM**:这轮只有下行方向(VM → 浏览器)。
- **大文件断点续传/分片**:假设开发过程中产出的文件不会大到需要分片,真遇到再评估。
- **文本文件内联预览**:这轮只做下载,预览留给有余力时再加(不阻塞"看得到、拿得到、删得掉"这个核心诉求)。

## 架构

```
浏览器（新增"文件"面板,树状展示）
   │ list_workspace_files / delete_workspace_file (WS,走已有 /ws)
   │ GET /api/vm/files/download?path=...&token=... (REST,走文件流,不塞进 WS JSON)
   ▼
控制面:复用子项目 2 的 WorkerConnectionRegistry,把请求转发给对应用户的 worker 连接
   │ list_dir / read_file / delete_file (WS,走 /worker/ws,跟 run_task 用同一条连接)
   ▼
opc worker:在 ~/opc_workspace/<project_id>/ 范围内执行,路径做规范化+前缀校验,
   不允许跳出这个目录
```

## 协议消息新增（worker ↔ 控制面,复用子项目 2 的 `/worker/ws` 连接）

| 方向 | type | 字段 |
|---|---|---|
| 控制面→worker | `list_dir` | `request_id`, `project_id`, `path`(相对路径,`""`=根目录) |
| worker→控制面 | `dir_listing` | `request_id`, `entries: [{name, is_dir, size, mtime}]` 或 `error` |
| 控制面→worker | `read_file` | `request_id`, `project_id`, `path` |
| worker→控制面 | `file_content` | `request_id`, `content_base64` 或 `error` |
| 控制面→worker | `delete_file` | `request_id`, `project_id`, `path` |
| worker→控制面 | `delete_result` | `request_id`, `ok`, `error` |

`request_id` 是这一轮新增的多路复用 key(跟子项目 2 的 `task_id` 是同一个思路——一条 worker 连接上可能同时有"任务执行"和"文件浏览"两类请求在途,用 `request_id` 而不是复用 `task_id` 避免语义混淆)。

## 控制面 ↔ 浏览器接口

- WS 类型 `list_workspace_files`(`{project_id, path}`)→ 转发 `list_dir` 给对应 worker,等 `dir_listing` 响应,包成 `ack` 回给浏览器。
- WS 类型 `delete_workspace_file`(`{project_id, path}`)→ 转发 `delete_file`,等 `delete_result`,包成 `ack`。
- 新 REST 端点 `GET /api/vm/files/download`(query: `project_id`, `path`；`Authorization: Bearer <token>`)→ 转发 `read_file` 给对应 worker,拿到 `content_base64` 后解码,以文件流(`Content-Disposition: attachment`)回给浏览器——用 REST 不用 WS,是因为文件内容可能比较大,不适合塞进一条 JSON 消息常驻内存,REST 响应可以流式写出。

这两类 WS 类型都要走子项目 1 之前那轮已经建好的 project 归属校验（`ProjectService.assert_access`）,防止用户跨 project_id explorer 别人的文件——这是复用现有机制,不是本轮新增。

## Worker 侧安全边界

worker 收到 `list_dir`/`read_file`/`delete_file` 的 `path` 参数后,统一走一个路径解析函数:

```python
def _resolve_safe_path(workspace_root: Path, relative_path: str) -> Path:
    """把 relative_path 解析到 workspace_root 下,拒绝任何跳出 workspace_root 的路径。"""
    candidate = (workspace_root / relative_path).resolve()
    if not candidate.is_relative_to(workspace_root.resolve()):
        raise ValueError("path escapes workspace root")
    return candidate
```

任何解析失败(包括 `../../etc/passwd` 之类的路径穿越)都要在 worker 侧直接拒绝,回一个 `error` 响应,不能让请求打到 workspace 目录之外——这是本轮新增功能自己的安全底线,不能重复"现有 `opc/layer4_tools/file_ops.py` 对绝对路径零校验"这个已知的老问题(那个问题本身不在这轮修复范围内,但**新写的这段代码不能重复同样的错误**)。

## 前端

工作区新增"文件"面板(新增导航或者作为 `ContextPanel` 的一个新 tab,复用现有 tab 切换模式):树状列出目录内容,双击文件夹展开/收起,双击文件触发下载,每个条目有"删除"按钮(二次确认弹窗,复用现有 `org-create-backdrop`/`org-create-modal` 弹窗样式)。

## 测试计划

- worker 侧 `_resolve_safe_path` 单测:正常相对路径解析正确;`../`、绝对路径、symlink 指向外部等路径穿越尝试必须被拒绝。
- worker 侧 `list_dir`/`read_file`/`delete_file` 单测(mock 本地文件系统,用临时目录)。
- 控制面转发逻辑单测:mock `WorkerConnectionRegistry`,测请求正确转发、`request_id` 多路复用正确匹配对应响应,测未连接 worker 时的报错路径。
- 下载端点集成测试:mock worker 响应,确认 HTTP 响应体是文件内容(带正确 `Content-Disposition`)而不是 JSON 包装;确认跨用户 project_id 被 `assert_access` 拦截返回 403/错误,不转发给 worker。
- 端到端(复用前几个子项目已经跑起来的真实 VM):在 VM 上创建几个文件/子目录(可以是子项目 2 端到端验证时 agent 已经产出的),浏览器里能看到、能下载、能删除。

## Open Questions

- 文件面板要不要跟现有 `ContextPanel` 的哪个已有 tab 合并,还是单独新开一个 —— 交给写实施计划时对着当前 `ContextPanel.tsx` 的实际 tab 结构决定,这轮设计不预判具体 UI 挂载点。
