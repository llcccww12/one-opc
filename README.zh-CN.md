<h1 align="center">One-OPC</h1>

<p align="center">
  <b>AI Agent 协作平台 — 本地部署，开箱即用</b>
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-111827?style=flat-square">
</p>

---

One-OPC 是一个本地部署的 AI Agent 协作平台。你用自然语言描述任务，系统自动拆解、分配给多个 AI Agent 并行执行，最终交付结果。

**核心特性：**
- 🏗️ **自动组建团队** — 根据任务自动招募角色化的 AI 员工
- ⚙️ **自动执行** — 任务分配、协作、审核、交付全自动
- 🖥️ **本地运行** — 所有数据和执行都在你的电脑上，无需云服务
- 🌐 **可视化界面** — Office UI 实时展示 Agent 工作状态、看板、对话

## 快速开始

### 前置条件

- **Python >= 3.10**
- **Node.js >= 18**（用于安装 Claude Code CLI）
- **Claude Code CLI**（核心 AI 运行时）

### 一键安装

```bash
git clone https://github.com/llcccww12/one-opc.git
cd one-opc
bash scripts/install.sh
```

安装脚本会自动：
1. 检查 Python 版本
2. 安装 OPC 及其依赖
3. 检测并安装 Claude Code CLI（如果没有）
4. 初始化配置

### 手动安装

```bash
git clone https://github.com/llcccww12/one-opc.git
cd one-opc
pip install -e .

# 安装 Claude Code CLI（如果没有）
npm install -g @anthropic-ai/claude-code

# 初始化
opc init

# 配置 API Key
opc setup
```

### 启动

```bash
opc ui
```

打开浏览器访问 **http://localhost:8765**

## 使用方式

### 方式 1：Office UI（推荐）

```bash
opc ui
```

在浏览器中：
1. 点击左下角齿轮图标配置 API Key
2. 在 Workspace 页面输入任务描述
3. 选择 Task Mode（单 Agent）或 Company Mode（多 Agent 协作）
4. Agent 自动开始工作，你可以在看板和对话中实时跟踪进度

### 方式 2：命令行

```bash
# Task Mode — 单 Agent 执行
opc chat -p demo --mode task --agent claude_code "帮我写一个 Python 爬虫"

# Company Mode — 多 Agent 协作
opc chat -p demo --mode company --company-profile corporate "帮我做一个博客网站"
```

## 配置

配置文件位于 `~/.opc/config/`

| 文件 | 用途 |
|------|------|
| `llm_config.yaml` | API Key、模型、Base URL |
| `system_config.yaml` | 系统级设置 |
| `agent_config.yaml` | Agent 配置 |
| `company_orgs/` | 公司架构模板 |

### 配置 API Key

编辑 `~/.opc/config/llm_config.yaml`：

```yaml
api_key: "sk-ant-xxx..."
api_base: ""  # 留空使用官方 API，或填写第三方中转地址
default_model: "claude-sonnet-4-20250514"
```

或通过命令行：

```bash
opc setup
```

## 项目结构

```
one-opc/
├── opc/                          # 核心代码
│   ├── cli/                      # 命令行接口
│   ├── engine.py                 # 核心引擎
│   ├── layer0_interaction/       # 消息总线
│   ├── layer1_perception/        # 上下文加载
│   ├── layer2_organization/      # 公司模式运行时
│   ├── layer3_agent/             # Agent 运行时
│   ├── layer4_tools/             # 工具集（Shell、文件、浏览器等）
│   ├── layer5_memory/            # 记忆与技能库
│   ├── layer6_observability/     # 事件与日志
│   └── plugins/office_ui/        # Office UI 插件
│       ├── frontend_src/         # React 前端源码
│       └── frontend_dist/        # 构建产物
├── scripts/
│   └── install.sh                # 一键安装脚本
├── tests/                        # 测试
├── Makefile                      # 构建命令
└── pyproject.toml                # Python 包配置
```

## 常见问题

### Claude Code CLI 找不到？

```bash
npm install -g @anthropic-ai/claude-code
claude --version  # 确认安装成功
```

### API Key 怎么获取？

1. 前往 [Anthropic Console](https://console.anthropic.com/settings/keys) 申请
2. 或使用第三方中转服务提供的 Key + Base URL

### 端口被占用？

```bash
opc ui --port 8766
```

### 数据存在哪里？

- `~/.opc/` — 配置、记忆、数据库
- `~/.opc/ui_state.db` — UI 状态（聊天、看板）
- `~/.opc/global.db` — 会话、事件、执行记录
- `OpenOPC-main_workplace/` — Agent 工作目录

## License

MIT
