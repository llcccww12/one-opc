export interface HelpSection {
  id: string
  title: string
  body: string
}

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: 'quick-start',
    title: '快速开始',
    body: `# 快速开始

OpenOPC 有两种执行模式：

- **Task Mode（任务模式）** — 单个 agent/会话，类似 LobeChat 的直接对话。
- **Company Mode（公司模式）** — 把一份需求（brief）拆解成一张按角色分工的工作项图，由一个模拟的公司团队去执行。

左侧图标栏对应三个主要页面：

| 图标 | 页面 | 作用 |
| --- | --- | --- |
| Workspace | 工作台 | 会话列表、聊天、看板（Board 抽屉） |
| Office | 办公室 | 可视化的 2D 办公室场景，查看 agent 实时状态 |
| Org | 组织 | 团队结构、角色、运行时团队、架构市场、Connectors |

命令行等价操作：

\`\`\`bash
opc chat -p demo --mode task --agent native "..."         # 任务模式
opc chat -p demo --mode company --company-profile corporate "..."   # 公司模式
opc ui                                                     # 启动本 Office UI
\`\`\`
`,
  },
  {
    id: 'create-org',
    title: '创建一个组织',
    body: `# 创建一个组织

进入左侧 **Org** 页面后，右上角有一个 **Organization** 下拉框和 **+ New organization** 按钮。

## 方式一：从零创建

1. 点击 **+ New organization**。
2. **第 1 步 · Name**：填写组织名称。
3. **第 2 步 · Members**：逐个添加成员——名称、职责（responsibility）、可选的自定义 prompt、以及“汇报给谁”（reports to）。第一个成员默认是负责人（Owner），后续成员可以选择汇报给已添加的任意前置成员，从而搭建出层级结构。
4. **第 3 步 · Review**：确认预览无误后点击 **Create organization**。

创建成功会自动保存为一个"自定义组织"（custom org）并立刻切换为当前激活的组织,无需手动保存。

## 方式二：套用预设架构

在 Org 页面的 **Architecture** 子标签里有一个预设架构市场（Pipeline / Hub & Spoke / Review Loop / Hierarchical / Flat Team 等协作模式）。点击某个预设卡片 → Preview 预览其角色构成 → **Apply** 即可把这套角色团队合并进当前的自定义组织。

## Corporate 与自定义组织的区别

- **Corporate** 是内置的默认组织，**只读**，不能编辑角色、不能分配 Connector 权限。
- 只有**自定义组织**（New organization 创建的，或从 Corporate 派生保存的）才能编辑角色、工具权限、Connectors 授权等。
- 右上角的 Organization 下拉框可以随时在 Corporate 与已保存的多个自定义组织之间切换；每个自定义组织对应磁盘上的一个独立 YAML 文件（\`.opc/config/company_orgs/org_<id>_config.yaml\`）。

创建/编辑好组织后，可以在其他子标签查看结果：**Team**（角色列表与详情）、**Runtime**（当前运行时的团队与在线 agent）、**Employees**（人才库）。
`,
  },
  {
    id: 'connectors-mcp',
    title: 'Connectors / MCP 接入',
    body: `# Connectors（MCP 服务器）

Connector 就是一个已配置并已连接的 **MCP（Model Context Protocol）服务器**。连接后，MCP 服务器暴露的工具会被自动发现并注册进 OPC 的全局工具库（ToolRegistry），但**注册进工具库 ≠ 角色马上就能用**——这是最容易踩的坑，见下方"授权给角色"一节。

## 在哪里操作

**Org → Architecture → Connectors** 区块。

## 添加一个 Connector

点击 **Add Connector**，有两种类型：

### 本地（local，通过子进程 stdio 通信）

| 字段 | 说明 |
| --- | --- |
| Name | Connector 的唯一标识，也是工具名前缀（见下文） |
| Command | 启动 MCP server 的可执行命令，按空格分词，例如 \`npx -y @modelcontextprotocol/server-github\` |
| Environment variables | 可选，每行一条 \`KEY=value\`，常用来传 API Token |
| Tool filter | 可选，逗号分隔的工具名白名单；留空 = 暴露该服务器的全部工具 |

等价的持久化配置（会自动写入，通常不需要手动编辑）：

\`\`\`yaml
mcp_servers:
  - name: github
    type: local
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxx"
    tools_filter: []
    enabled: true
    startup_timeout: 30
\`\`\`

### 远程（remote，通过 StreamableHTTP / SSE）

| 字段 | 说明 |
| --- | --- |
| Name | 同上 |
| URL | 远程 MCP server 地址 |
| Headers | 可选，每行一条 \`Key: value\`，常用来传 \`Authorization: Bearer ...\` |
| Tool filter | 同上 |

\`\`\`yaml
mcp_servers:
  - name: linear
    type: remote
    url: "https://mcp.example.com/sse"
    headers:
      Authorization: "Bearer sk-xxx"
    tools_filter: ["create_issue", "list_issues"]
\`\`\`

点击 **Connect** 后会立即尝试连接；连接失败（命令不存在、URL 不通等）不会写入任何配置，会直接在界面上报错，可以修正后重试。连接成功才会保存并注册工具。

## 工具命名规则

注册进工具库的名字会带上 Connector 名前缀：\`{connector 名}_{原始工具名}\`（非字母数字字符会被替换成下划线）。例如 Connector 叫 \`github\`、MCP 服务器暴露的工具叫 \`create_issue\`，注册后的工具名就是 \`github_create_issue\`。在下面"授权给角色"和角色的 \`tools\` 列表里看到的都是这个带前缀的名字。

## 授权给角色（关键一步）

每个角色的 \`tools\` 字段是一份**白名单**——只要这份列表非空，角色就只能使用列表里的工具，新连接的 Connector 工具**不会自动**出现在任何角色手里。

操作方式：在 Connector 卡片上点击 **Manage roles**，勾选需要用到这些工具的角色，保存后对应角色的 \`tools\` 列表会被追加上这些工具名；取消勾选则会从该角色的 \`tools\` 里移除。

限制：**Manage roles 只能在自定义组织（custom org）里使用**，Corporate 是只读的（可以连接 Connector，但无法把它分配给角色）。如果目前用的是 Corporate，先按上一节"创建一个组织"里的方法建一个自定义组织。

> 注：Team 标签里角色详情面板的 "Tools" 复选框目前只列出内置工具分类（Files / Shell / Web / TODOs / Browser），MCP 工具不会在那里显示为可勾选项，但会计入右上角的工具计数。要查看/调整某个 Connector 的角色授权，请回到 Connectors 卡片用 Manage roles，而不是 Team 标签。

## 移除一个 Connector

Connector 卡片上的 **Remove** 会依次执行：断开连接 → 从工具库注销该服务器注册的所有工具 → 从配置里删除这条 Connector → 从所有角色的 \`tools\` 列表里清理掉这些工具名，避免留下失效的授权残留。

## 配置持久化位置

Connector 配置保存在 \`.opc/config/system_config.yaml\` 的 \`system.mcp_servers\` 下（跟角色/组织的 YAML 是分开的文件）。重启 \`opc ui\` 后引擎会在启动时自动重新连接所有已配置的 Connector 并重新注册工具，不需要手动重连。
`,
  },
  {
    id: 'roles-tools',
    title: '角色与工具权限',
    body: `# 角色与工具权限

在 **Org → Team** 标签里可以查看每个角色，点开角色详情面板能看到：

- 基本信息：名称、职责描述、系统 prompt。
- **Tools** 复选框：内置工具按类别分组（Files / Shell / Web / TODOs / Browser），勾选即加入该角色的 \`tools\` 白名单。

核心规则：\`tools\` 是**白名单**。只要这个列表非空，角色就只能调用列表里的工具；真实的组织模板通常都会给每个角色配置一份非空的 \`tools\` 列表，所以新增的能力（无论是内置工具还是 MCP Connector 的工具）都需要显式加进去才会生效——见「Connectors / MCP 接入」一节的"授权给角色"。

只有自定义组织（custom org）的角色可以编辑；Corporate 默认组织的角色是只读的。
`,
  },
  {
    id: 'channels',
    title: 'Channels（消息渠道）',
    body: `# Channels

Channels 是外部消息渠道的接入状态（Slack、Discord、Telegram、Feishu、DingTalk、Matrix、QQ、WhatsApp、Mochat、Email 等），显示在 **Org → Architecture → Channels** 区块。

每个渠道是一个可选的安装扩展，例如：

\`\`\`bash
pip install -e ".[channels-slack]"
\`\`\`

安装对应依赖 + 在配置里补上该渠道所需的凭证（如 Bot Token）后，渠道才会显示为已启用；否则会显示为灰色/未配置状态。所有渠道最终都会接入同一条消息总线（\`opc/layer0_interaction\`），跟 CLI、Office UI 是同一条执行路径，只是入口不同。
`,
  },
  {
    id: 'marketplace',
    title: '架构市场 / Installed Packages',
    body: `# 架构市场与 Installed Packages

**Org → Architecture** 里除了 Connectors，还有两块：

- **架构预设市场**：内置的一批协作模式模板（Pipeline / Hub & Spoke / Review Loop / Hierarchical / Flat Team），可以按分类、协作模式、关键字搜索，Preview 后一键 Apply 合并进当前自定义组织。
- **Installed Packages**：以命名空间方式安装的外部角色/工作项模板包，可以通过 **Import** 按钮导入本地路径，或在这里卸载（Uninstall）已安装的包——卸载会移除该包带来的角色和工作项模板。

跟 Connectors 一样，这些操作都只能在自定义组织里进行，Corporate 是只读的。
`,
  },
  {
    id: 'faq',
    title: '常见问题',
    body: `# 常见问题

**Q: 我重启了 \`opc ui\`，配置会丢吗？**
不会。角色/组织配置在 \`.opc/config/company_orgs/org_<id>_config.yaml\`，系统级配置（包括 Connectors）在 \`.opc/config/system_config.yaml\`，都是启动时自动加载、修改时自动持久化。

**Q: Connector 显示已连接，但角色好像用不了它的工具？**
先确认该工具名已经出现在角色的 \`tools\` 列表里（通过 Connector 卡片的 Manage roles 查看/勾选），再确认当前操作的是自定义组织而不是只读的 Corporate。

**Q: 为什么 Channels 里很多渠道是灰色的？**
渠道是可选安装的扩展（\`pip install -e ".[channels-<name>]"\`），装好依赖并配置好凭证后才会点亮。

**Q: 日志/运行状态在哪里看？**
Workspace 页面的会话聊天记录里能看到 agent 的实时输出；左侧图标栏底部的 **Dev Tools** 面板可以看到事件流（Events）和进化流水线（Evolution Pipeline）等底层调试信息。

**Q: 配置文件/运行数据都存在哪？**
默认都在项目内的 \`.opc/\` 目录（可以用 \`OPC_HOME\` 环境变量迁移到别处）；agent 产出的交付物在 \`../OpenOPC_workplace/<project>/\` 下。
`,
  },
]
