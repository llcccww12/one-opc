"""Connectors (MCP server) service.

A "connector" is a configured MCP server (opc.mcp_client.MCPManager). Adding one
connects immediately and registers its discovered tools into the shared
ToolRegistry; the tools only become callable by a role once that role's
`tools` allowlist is extended to include them via `set_connector_roles`.
"""

from __future__ import annotations

from typing import Any

from opc.core.config import MCPServerConfig

from .context import OfficeServiceContext
from .models import ServiceError, ServiceEvent, ServiceResult


class ConnectorsService:
    def __init__(self, context: OfficeServiceContext) -> None:
        self.context = context

    def _ensure_custom_org_editable(self) -> None:
        if not self.context.is_custom_org_editable():
            raise ServiceError(
                "org_read_only",
                "Corporate organization is read-only. Select or create a saved custom org before editing.",
            )

    def _mcp_manager(self) -> Any:
        manager = getattr(self.context.engine, "mcp_manager", None)
        if manager is None:
            raise ServiceError("mcp_unavailable", "MCP support is not initialized on this engine")
        return manager

    async def list_connectors(self) -> list[dict[str, Any]]:
        manager = getattr(self.context.engine, "mcp_manager", None)
        servers = list(getattr(self.context.engine.config.system, "mcp_servers", []) or [])
        connectors: list[dict[str, Any]] = []
        for server in servers:
            connected = bool(manager and manager.is_connected(server.name))
            connectors.append({
                "connector_id": server.name,
                "name": server.name,
                "connector_type": server.type,
                "description": f"{server.type} MCP server" + (f" ({server.url})" if server.type == "remote" and server.url else ""),
                "actions": manager.get_tool_names(server.name) if manager else [],
                "status": "connected" if connected else "disconnected",
            })
        return connectors

    async def add_connector(self, data: dict[str, Any]) -> ServiceResult:
        name = str(data.get("name", "") or "").strip()
        if not name:
            raise ServiceError("missing_name", "name required")
        system_cfg = self.context.engine.config.system
        if any(server.name == name for server in system_cfg.mcp_servers):
            raise ServiceError("connector_exists", f"Connector '{name}' already exists", {"name": name})
        connector_type = str(data.get("connector_type", "local") or "local").strip()
        if connector_type not in {"local", "remote"}:
            raise ServiceError("invalid_type", "type must be 'local' or 'remote'")
        env = {str(key): str(value) for key, value in dict(data.get("env") or {}).items()}
        tools_filter = [str(item).strip() for item in list(data.get("tools_filter") or []) if str(item).strip()]
        manager = self._mcp_manager()

        if connector_type == "local":
            command = [str(item).strip() for item in list(data.get("command") or []) if str(item).strip()]
            if not command:
                raise ServiceError("missing_command", "command required for a local connector")
            url, headers = "", {}
            try:
                conn = await manager.connect_local(name, command, env=env or None)
            except Exception as exc:
                raise ServiceError("connector_connect_failed", str(exc), {"name": name}) from exc
        else:
            url = str(data.get("url", "") or "").strip()
            if not url:
                raise ServiceError("missing_url", "url required for a remote connector")
            headers = {str(key): str(value) for key, value in dict(data.get("headers") or {}).items()}
            command = []
            try:
                conn = await manager.connect_remote(name, url, headers=headers or None)
            except Exception as exc:
                raise ServiceError("connector_connect_failed", str(exc), {"name": name}) from exc

        tools = await manager.register_tools(conn, tool_filter=set(tools_filter))
        new_server = MCPServerConfig(
            name=name,
            type=connector_type,
            command=command,
            url=url,
            headers=headers,
            env=env,
            tools_filter=tools_filter,
        )
        async with self.context.config_lock:
            system_cfg.mcp_servers.append(new_server)
            await self._persist_config()
            self._persist_system_config()
        events = await self._org_info_events()
        return ServiceResult({
            "connector": {
                "connector_id": name,
                "name": name,
                "connector_type": connector_type,
                "description": f"{connector_type} MCP server",
                "actions": [tool.name for tool in tools],
                "status": "connected",
            },
            "action": "connector_added",
        }, events)

    async def remove_connector(self, connector_id: str) -> ServiceResult:
        connector_id = str(connector_id or "").strip()
        if not connector_id:
            raise ServiceError("missing_connector_id", "connector_id required")
        system_cfg = self.context.engine.config.system
        target = next((server for server in system_cfg.mcp_servers if server.name == connector_id), None)
        if target is None:
            raise ServiceError("connector_not_found", "Connector not found", {"connector_id": connector_id})

        manager = getattr(self.context.engine, "mcp_manager", None)
        tool_names = manager.get_tool_names(connector_id) if manager else []
        if manager is not None:
            await manager.disconnect(connector_id)
        tool_registry = getattr(self.context.engine, "tool_registry", None)
        if tool_registry is not None:
            for tool_name in tool_names:
                tool_registry.unregister(tool_name)

        async with self.context.config_lock:
            system_cfg.mcp_servers = [server for server in system_cfg.mcp_servers if server.name != connector_id]
            if tool_names:
                for role in self.context.engine.config.org.roles:
                    role.tools = [tool_name for tool_name in (role.tools or []) if tool_name not in tool_names]
            await self._persist_config()
            self._persist_system_config()
        events = await self._org_info_events()
        return ServiceResult({"connector_id": connector_id, "action": "connector_removed"}, events)

    async def set_connector_roles(self, connector_id: str, role_ids: list[str]) -> ServiceResult:
        self._ensure_custom_org_editable()
        connector_id = str(connector_id or "").strip()
        if not connector_id:
            raise ServiceError("missing_connector_id", "connector_id required")
        manager = self._mcp_manager()
        if not manager.is_connected(connector_id):
            raise ServiceError("connector_not_connected", "Connector must be connected to assign its tools to roles", {"connector_id": connector_id})
        tool_names = manager.get_tool_names(connector_id)
        wanted_role_ids = {str(role_id).strip() for role_id in (role_ids or []) if str(role_id).strip()}

        async with self.context.config_lock:
            for role in self.context.engine.config.org.roles:
                role_id = str(getattr(role, "id", getattr(role, "role_id", "")) or "")
                current = list(role.tools or [])
                if role_id in wanted_role_ids:
                    role.tools = current + [tool_name for tool_name in tool_names if tool_name not in current]
                else:
                    role.tools = [tool_name for tool_name in current if tool_name not in tool_names]
            await self._persist_config()
        events = await self._org_info_events()
        return ServiceResult({
            "connector_id": connector_id,
            "role_ids": sorted(wanted_role_ids),
            "action": "connector_roles_updated",
        }, events)

    async def _persist_config(self) -> None:
        if self.context.persist_runtime_config is not None:
            self.context.persist_runtime_config()
        else:
            self.context.engine.config.save()
        self.context.rebind_config(self.context.engine.config)
        org = getattr(self.context.engine, "org_engine", None)
        if org and hasattr(org, "reload_from_config"):
            org.reload_from_config()

    def _persist_system_config(self) -> None:
        # `persist_runtime_config` skips writing system_config.yaml while in
        # org/custom mode (it only rewrites the active org's own YAML), so
        # mcp_servers needs an explicit config.save() to survive a restart.
        self.context.engine.config.save(config_dir=self.context.opc_home / "config")

    async def _org_info_events(self) -> list[ServiceEvent]:
        from .org import OrgService

        return (await OrgService(self.context).info(include_events=True)).events
