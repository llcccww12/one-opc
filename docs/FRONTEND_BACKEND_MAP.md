# OpenOPC 前后端功能关联清单

> 生成时间：2026-07-10
> 用途：换 UI 时确保前后端功能对应完整

---

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (React)                       │
│  App.tsx (中枢) → wsClient.ts (60+ WS方法)              │
│  Stores: ChatStore, BoardStore, SessionStore, ProjectStore│
└──────────────────────┬──────────────────────────────────┘
                       │ WebSocket (ws://localhost:8765/ws)
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   WS Handler (ws_handler.py)             │
│  路由消息 → Service 层                                   │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   Service Layer                          │
│  agent.py | kanban.py | session.py | org.py             │
│  talent.py | market.py | comms.py | runtime.py          │
│  work_item.py | project.py | context.py                 │
└─────────────────────────────────────────────────────────┘
```

---

## 一、项目管理

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 列出项目 | ProjectSelector | `list_projects` | `_handle_list_projects` | `project.list` | `ack` |
| 创建项目 | ProjectSelector | `create_project` | `_handle_create_project` | `project.create` | `ack` |
| 删除项目 | ProjectSelector | `delete_project` | `_handle_delete_project` | `project.delete` | `ack` |
| 切换项目 | ProjectSelector | `switch_project` | `_handle_switch_project` | `project.switch` | `project_switched`, `project_index_push` |

---

## 二、会话管理（Session）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 创建会话 | SessionSidebar, WorkspacePage | `create_session` | `_handle_create_session` | `session.create` | `session_created` |
| 发送消息 | MessageComposer, ContextPanel | `session_send` | `_handle_session_send` | `chat_store`, `_process_session_message` | `session_message`, `session_progress` |
| 获取详情 | ExecutionPanel, ContextPanel | `session_detail` | `_handle_session_detail` | `chat_store` | `session_detail` |
| 更新标题 | TaskHeaderBar, ContextPanel | `session_update_title` | `_handle_session_update_title` | `session.rename` | `session_title_updated` |
| 更新配置 | TaskHeaderBar, ContextPanel | `session_update_config` | `_handle_session_update_config` | `session.update_config` | `session_updated` |
| 删除会话 | SessionSidebar | `session_delete` | `_handle_session_delete` | `session.delete` | `ack` |
| 停止会话 | EscalationPanel, AgentWorkPanel | `session_stop` | `_handle_session_stop` | `_cancel_task_tree` | `board_task_status_changed`, `session_message` |
| 恢复会话 | EscalationPanel, AgentWorkPanel | `session_resume` | `_handle_session_resume` | `_process_session_message` | `session_message`, `session_progress` |
| 完成会话 | EscalationPanel, AgentWorkPanel | `session_complete` | `_handle_session_complete` | `session.complete` | `ack` |
| 秘书发送 | MessageComposer, SessionSidebar | `secretary_send` | `_handle_secretary_send` | `engine.process_secretary_message` | `session_message` |
| 会话进度 | — | — | — | — | `session_progress` (推送) |
| 子会话 | — | — | — | — | `child_session_created` (推送) |

---

## 三、Agent 管理

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 创建 Agent | App.tsx | `create_agent` | `_handle_create_agent` | `agent_store.create_agent` | `agent_spawned` (event) |
| 删除 Agent | App.tsx | `delete_agent` | `_handle_delete_agent` | `agent.delete` | `snapshot`, `org_info` |
| 移动 Agent | App.tsx | `move_agent` | `_handle_move_agent` | `agent.move` | `snapshot` |
| Agent 详情 | App.tsx | `get_agent_detail` | `_handle_get_agent_detail` | `agent.detail` | `ack` |
| Agent 负载 | — | `agent_workload` | `_handle_agent_workload` | `agent_store.get_all` | `ack` |
| Agent 运行时状态 | — | — | — | — | `agent_runtime_update` (推送) |
| 跨办公室协作 | — | `cross_office_collab` | `_handle_cross_office` | — | `cross_office_collab` (广播) |

---

## 四、执行模式

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 设置模式 | App.tsx | `set_execution_mode` | `_handle_set_mode` | `_apply_mode_switch` | `execution_mode_resolved`, `snapshot`, `org_info` |
| 运行任务 | App.tsx | `run_task` | `_handle_run_task` | `_run_task` | `ack` |

---

## 五、看板（Kanban）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 创建看板 | App.tsx | `kanban_create_board` | `_handle_kanban_create_board` | `_engine_for_request` | `kanban_board_created` |
| 创建任务 | App.tsx | `kanban_create_task` | `_handle_kanban_create_task` | `kanban.create_task` | `board_task_created` |
| 更新任务 | — | `kanban_update_task` | `_handle_kanban_update_task` | `kanban.update_task` | `ack` |
| 移动任务 | KanbanBoardView | `kanban_move_task` | `_handle_kanban_move_task` | `kanban.move_task` | `board_task_moved` |
| 删除看板 | — | `kanban_delete_board` | `_handle_kanban_delete_board` | `_engine_for_request` | `ack` |
| 删除任务 | — | `kanban_delete_task` | `_handle_kanban_delete_task` | `kanban.delete_task` | `ack` |
| 分配任务 | App.tsx | `kanban_assign` | `_handle_kanban_assign` | `kanban.assign` | `ack` |
| 更新状态 | App.tsx | `kanban_status` | `_handle_kanban_status` | `kanban.status` | `board_task_status_changed` |
| 切换视图 | — | `kanban_switch_view` | `_handle_kanban_switch_view` | `build_company_kanban_projection` | `kanban_view_data` |
| 看板数据推送 | — | — | — | — | `kanban_view_data` (推送) |

---

## 六、组织管理（Org）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 获取组织信息 | OrgTab | `org_info` | `_handle_org_info` | `org.info` | `org_info` |
| 添加角色 | StructureEditor, TeamView | `add_role` | `_handle_add_role` | `org.add_role` | `ack`, `org_info` |
| 批量添加角色 | StructureEditor, TeamView | `bulk_add_roles` | `_handle_bulk_add_roles` | `org.bulk_add_roles` | `ack`, `org_info` |
| 更新角色 | RoleTable, RoleInspector | `update_role` | `_handle_update_role` | `org.update_role` | `ack`, `org_info` |
| 删除角色 | RoleTable, StructureEditor | `delete_role` | `_handle_delete_role` | `org.delete_role` | `ack`, `org_info` |
| 更新策略 | DelegationStrategyPanel | `update_org_strategy` | `_handle_update_org_strategy` | `org.update_org_strategy` | `ack`, `org_info` |
| 更新运行策略 | DelegationStrategyPanel | `update_runtime_policy` | `_handle_update_runtime_policy` | `org.update_runtime_policy` | `ack`, `org_info` |
| 重置架构 | TeamView | `reset_architecture` | `_handle_reset_architecture` | `org.reset_architecture` | `ack`, `org_info` |
| 导出配置 | ConfigImportExportPanel | `org_config_export` | `_handle_org_config_export` | `org.export_config` | `org_config_export` |
| 导入配置 | ConfigImportExportPanel | `org_config_import` | `_handle_org_config_import` | `_apply_org_config` | `org_config_import` |

---

## 七、保存的组织（Org Saved）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 列出保存 | OrgVersionSwitcher | `org_saved_list` | `_handle_org_saved_list` | `org.saved_list` | `org_saved_list` |
| 另存为 | OrgVersionSwitcher | `org_saved_save_as` | `_handle_org_saved_save_as` | `org.saved_save_as` | `org_saved_save_as` |
| 创建组织 | OrgCreateModal | `org_saved_create` | `_handle_org_saved_create` | `org.saved_create` | `org_saved_create` |
| 加载组织 | OrgVersionSwitcher | `org_saved_load` | `_handle_org_saved_load` | `_apply_org_config` | `org_saved_load` |
| 删除组织 | OrgVersionSwitcher | `org_saved_delete` | `_handle_org_saved_delete` | `org.saved_delete` | `org_saved_delete` |

---

## 八、人才市场（Talent）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 列出人才 | OrgTab | `talent_list` | `_handle_talent_list` | `talent.list` | `talent_list` |
| 扫描本地 | — | `talent_scan_local` | `_handle_talent_scan_local` | `talent.scan` | `talent_scan_local` |
| 导入人才 | — | `talent_import` | `_handle_talent_import` | `talent.import_repo` | `ack`, `talent_list` |
| 导入选中 | — | `talent_import_selected` | `_handle_talent_import_selected` | `talent.import_selected` | `ack`, `talent_list` |
| 雇佣人才 | EmployeesMarketplace, RecruitmentPanel | `talent_hire` | `_handle_talent_hire` | `talent.hire` | `ack`, `org_info` |
| 员工详情 | OrgTab | `employee_detail` | `_handle_employee_detail` | `talent.employee_detail` | `employee_detail` |
| 导入为Agent | OrgTab | `import_employee_as_agent` | `_handle_import_employee_as_agent` | `talent.import_employee_as_agent` | `ack`, `org_info` |

---

## 九、OPC Market

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 浏览市场 | OrgTab | `market_browse` | `_handle_market_browse` | `market.browse` | `market_browse` |
| 预览包 | ArchitectureMarketplace | `market_preview` | `_handle_market_preview` | `market.preview` | `market_preview` |
| 应用预设 | ArchitectureMarketplace | `market_apply_preset` | `_handle_market_apply_preset` | `market.apply_preset` | `ack` |
| 列出已安装 | — | `market_list_installed` | `_handle_market_list_installed` | `market.list_installed` | `market_list_installed` |
| 导出包 | ArchitectureMarketplace, TeamView | `market_export` | `_handle_market_export` | `market.export` | `ack` |
| 安装包 | ArchitectureMarketplace | `market_install` | `_handle_market_install` | `market.install` | `ack` |
| 卸载包 | ArchitectureMarketplace | `market_uninstall` | `_handle_market_uninstall` | `market.uninstall` | `ack` |

---

## 十、组织重组（Reorg）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 列出提案 | OrgTab | `reorg_list` | `_handle_reorg_list` | `engine.store.list_reorg_proposals` | `reorg_list` |
| 审批提案 | ArchitectureMarketplace | `reorg_decide` | `_handle_reorg_decide` | `engine.reorg_manager` | `ack`, `org_info` |

---

## 十一、通信（Comms）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 获取状态 | CommsPanel | `comms_state` | `_handle_comms_state` | `comms.state` | `comms_state` |
| 读取消息 | CommsPanel | `comms_read_message` | `_handle_comms_read_message` | `comms.read` | `comms_message` |
| 状态变更推送 | — | — | — | — | `comms_state_dirty` (推送) |

---

## 十二、恢复（Recovery）

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 恢复操作 | WorkItemRecoveryPanel | `recovery_action` | `_handle_recovery_action` | `runtime.recovery_action` | `recovery_status` |
| 恢复状态 | — | — | — | — | `recovery_status` (推送) |
| 恢复结果 | — | — | — | — | `recovery_result` (推送) |

---

## 十三、协作同步

| 功能 | 前端组件 | WS 请求类型 | 后端 Handler | 后端 Service | WS 响应类型 |
|------|----------|-------------|--------------|--------------|-------------|
| 协作同步 | App.tsx | `collab_sync` | `_handle_collab_sync` | `build_collab_sync` | `collab_sync_push` |
| 项目索引 | — | `project_index` | `_handle_project_index` | `build_project_index_sync` | `project_index_push` |

---

## 十四、心跳

| 功能 | WS 请求类型 | 后端 Handler | WS 响应类型 |
|------|-------------|--------------|-------------|
| 心跳 | `ping` | `_handle_ping` | `pong` |

---

## 十五、服务端推送事件（无需前端请求）

| 推送事件 | 说明 |
|----------|------|
| `snapshot` | 全局状态快照（Agent位置、状态等） |
| `event` | 通用事件 |
| `agent_runtime_update` | Agent运行时状态变更 |
| `worker_notification` | Worker通知 |
| `session_progress` | 会话进度更新 |
| `work_item_progress` | 工作项进度更新 |
| `board_task_created` | 看板任务创建 |
| `board_task_moved` | 看板任务移动 |
| `board_task_status_changed` | 看板任务状态变更 |
| `session_created` | 会话创建 |
| `session_updated` | 会话更新 |
| `session_message` | 会话消息 |
| `session_title_updated` | 会话标题更新 |
| `session_deleted` | 会话删除 |
| `child_session_created` | 子会话创建 |
| `project_switched` | 项目切换 |
| `project_deleted` | 项目删除 |
| `org_info` | 组织信息更新 |
| `kanban_view_data` | 看板视图数据 |
| `execution_mode_resolved` | 执行模式确认 |
| `cross_office_collab` | 跨办公室协作 |
| `collab_sync_push` | 协作同步推送 |
| `project_index_push` | 项目索引推送 |
| `recovery_status` | 恢复状态 |
| `recovery_result` | 恢复结果 |
| `comms_state_dirty` | 通信状态变更 |
| `talent_list` | 人才列表 |
| `talent_scan_local` | 本地人才扫描 |
| `employee_detail` | 员工详情 |
| `reorg_list` | 重组提案列表 |
| `market_browse` | 市场浏览 |
| `market_preview` | 市场预览 |
| `market_list_installed` | 已安装包列表 |
| `org_config_export` | 配置导出 |
| `org_config_import` | 配置导入 |
| `org_saved_list` | 已保存组织列表 |
| `org_saved_save_as` | 另存为结果 |
| `org_saved_create` | 创建组织结果 |
| `org_saved_load` | 加载组织结果 |
| `org_saved_delete` | 删除组织结果 |

---

## 十六、前端未使用的 wsClient 方法

以下方法在 wsClient.ts 中定义，但当前没有任何组件调用：

| 方法 | 说明 |
|------|------|
| `createFromTemplate` | 从模板创建Agent |
| `listAgents` | 列出Agent |
| `getAgentDetail` | 获取Agent详情 |
| `updateTaskStatus` | 更新任务状态（使用 `kanban_status` 代替） |
| `kanbanUpdateTask` | 更新看板任务 |
| `kanbanDeleteBoard` | 删除看板 |
| `kanbanDeleteTask` | 删除看板任务 |
| `kanbanSwitchView` | 切换看板视图 |
| `talentImport` | 导入人才仓库 |
| `talentScanLocal` | 扫描本地人才 |
| `talentImportSelected` | 导入选中人才 |
| `marketListInstalled` | 列出已安装市场包 |
| `projectIndex` | 项目索引 |

> 注意：这些方法后端都有处理，可能是历史遗留或尚未完成的功能。换 UI 时可选择性保留。
