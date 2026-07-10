"""Tests for opc.plugins.office_ui.services.connectors.ConnectorsService."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from opc.core.config import OPCConfig, RoleConfig
from opc.plugins.office_ui.services.connectors import ConnectorsService
from opc.plugins.office_ui.services.context import ModeState, OfficeServiceContext
from opc.plugins.office_ui.services.models import ServiceError


class _FakeMCPConn:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeToolDef:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeMCPManager:
    """Stand-in for opc.mcp_client.MCPManager — no real subprocess/socket I/O."""

    def __init__(self, *, fail_connect: bool = False, exposed_tools: list[str] | None = None) -> None:
        self.fail_connect = fail_connect
        self.exposed_tools = exposed_tools if exposed_tools is not None else ["echo"]
        self._registered: dict[str, list[str]] = {}

    async def connect_local(self, name, command, env=None, timeout=30.0):
        if self.fail_connect:
            raise RuntimeError("could not spawn process")
        return _FakeMCPConn(name)

    async def connect_remote(self, name, url, headers=None, timeout=30.0):
        if self.fail_connect:
            raise RuntimeError("could not reach server")
        return _FakeMCPConn(name)

    async def register_tools(self, conn, tool_filter=None):
        names = [f"{conn.name}_{tool}" for tool in self.exposed_tools if not tool_filter or tool in tool_filter]
        self._registered[conn.name] = names
        return [_FakeToolDef(name) for name in names]

    def get_tool_names(self, name: str) -> list[str]:
        return list(self._registered.get(name, []))

    def is_connected(self, name: str) -> bool:
        return name in self._registered

    async def disconnect(self, name: str) -> bool:
        return self._registered.pop(name, None) is not None


@contextmanager
def _build_context(mcp_manager: _FakeMCPManager | None = None, *, editable: bool = True):
    cfg = OPCConfig()
    if editable:
        cfg.org.company_profile = "custom"
        cfg.org.organization_id = "lab"
    org_engine = SimpleNamespace(config=cfg, reload_from_config=MagicMock())
    engine = SimpleNamespace(
        config=cfg,
        opc_home=Path("/nonexistent-test-opc-home"),
        org_engine=org_engine,
        talent_market=SimpleNamespace(config=cfg),
        tool_registry=MagicMock(),
        mcp_manager=mcp_manager if mcp_manager is not None else _FakeMCPManager(),
    )
    context = OfficeServiceContext(
        engine=engine,
        agent_store=MagicMock(),
        chat_store=MagicMock(),
        event_adapter=MagicMock(),
        mode_state=ModeState(exec_mode="org" if editable else "company", company_profile="custom" if editable else "corporate"),
    )
    context.persist_runtime_config = lambda: None
    # OPCConfig is a pydantic model — patch the class method rather than
    # assigning an instance attribute (pydantic rejects unknown fields).
    with patch.object(OPCConfig, "save") as save_mock:
        context.save_mock = save_mock
        yield context


def test_add_connector_connects_and_persists():
    async def run() -> None:
        with _build_context() as context:
            result = await ConnectorsService(context).add_connector({
                "name": "conn",
                "connector_type": "local",
                "command": ["python", "server.py"],
            })
            assert result.payload["connector"]["connector_id"] == "conn"
            assert result.payload["connector"]["actions"] == ["conn_echo"]
            assert result.payload["connector"]["status"] == "connected"
            assert [server.name for server in context.engine.config.system.mcp_servers] == ["conn"]
            # mcp_servers lives in SystemConfig, which persist_runtime_config's
            # org-mode branch never writes — must be persisted via config.save().
            context.save_mock.assert_called_once()

    asyncio.run(run())


def test_add_connector_does_not_persist_on_connect_failure():
    async def run() -> None:
        with _build_context(_FakeMCPManager(fail_connect=True)) as context:
            with pytest.raises(ServiceError) as exc:
                await ConnectorsService(context).add_connector({
                    "name": "conn",
                    "connector_type": "local",
                    "command": ["python", "server.py"],
                })
            assert exc.value.code == "connector_connect_failed"
            assert context.engine.config.system.mcp_servers == []
            context.save_mock.assert_not_called()

    asyncio.run(run())


def test_add_connector_rejects_duplicate_name():
    async def run() -> None:
        with _build_context() as context:
            service = ConnectorsService(context)
            await service.add_connector({"name": "conn", "connector_type": "local", "command": ["python", "server.py"]})
            with pytest.raises(ServiceError) as exc:
                await service.add_connector({"name": "conn", "connector_type": "local", "command": ["python", "other.py"]})
            assert exc.value.code == "connector_exists"

    asyncio.run(run())


def test_remove_connector_unregisters_tools_and_strips_role_allowlists():
    async def run() -> None:
        with _build_context() as context:
            context.engine.config.org.roles = [
                RoleConfig(id="analyst", name="Analyst", responsibility="Analyze.", tools=["conn_echo", "shell"]),
            ]
            service = ConnectorsService(context)
            await service.add_connector({"name": "conn", "connector_type": "local", "command": ["python", "server.py"]})

            result = await service.remove_connector("conn")

            assert result.payload["action"] == "connector_removed"
            assert context.engine.config.system.mcp_servers == []
            assert context.engine.config.org.roles[0].tools == ["shell"]
            context.engine.tool_registry.unregister.assert_called_once_with("conn_echo")
            assert context.save_mock.call_count == 2

    asyncio.run(run())


def test_remove_connector_missing_raises():
    async def run() -> None:
        with _build_context() as context:
            with pytest.raises(ServiceError) as exc:
                await ConnectorsService(context).remove_connector("nope")
            assert exc.value.code == "connector_not_found"

    asyncio.run(run())


def test_set_connector_roles_adds_and_removes_tool_allowlist_entries():
    async def run() -> None:
        with _build_context() as context:
            context.engine.config.org.roles = [
                RoleConfig(id="r1", name="R1", responsibility="Work.", tools=["shell"]),
                RoleConfig(id="r2", name="R2", responsibility="Work.", tools=[]),
            ]
            service = ConnectorsService(context)
            await service.add_connector({"name": "conn", "connector_type": "local", "command": ["python", "server.py"]})

            await service.set_connector_roles("conn", ["r1"])
            roles = {role.id: role for role in context.engine.config.org.roles}
            assert roles["r1"].tools == ["shell", "conn_echo"]
            assert roles["r2"].tools == []

            await service.set_connector_roles("conn", ["r2"])
            roles = {role.id: role for role in context.engine.config.org.roles}
            assert roles["r1"].tools == ["shell"]
            assert roles["r2"].tools == ["conn_echo"]

    asyncio.run(run())


def test_set_connector_roles_requires_connected_connector():
    async def run() -> None:
        with _build_context() as context:
            with pytest.raises(ServiceError) as exc:
                await ConnectorsService(context).set_connector_roles("never-connected", ["r1"])
            assert exc.value.code == "connector_not_connected"

    asyncio.run(run())


def test_set_connector_roles_rejects_corporate_readonly_org():
    async def run() -> None:
        with _build_context(editable=False) as context:
            with pytest.raises(ServiceError) as exc:
                await ConnectorsService(context).set_connector_roles("conn", ["r1"])
            assert exc.value.code == "org_read_only"

    asyncio.run(run())


def test_list_connectors_reports_live_status():
    async def run() -> None:
        with _build_context() as context:
            service = ConnectorsService(context)
            assert await service.list_connectors() == []

            await service.add_connector({"name": "conn", "connector_type": "local", "command": ["python", "server.py"]})
            connectors = await service.list_connectors()
            assert len(connectors) == 1
            assert connectors[0]["connector_id"] == "conn"
            assert connectors[0]["status"] == "connected"
            assert connectors[0]["actions"] == ["conn_echo"]

            await service.remove_connector("conn")
            assert await service.list_connectors() == []

    asyncio.run(run())
