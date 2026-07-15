from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from opc.core.config import EmployeeConfig, OPCConfig, RoleConfig
from opc.layer2_organization.org_engine import OrgEngine


def _make_handler(cfg: OPCConfig):
    from opc.plugins.office_ui.ws_handler import WSHandler

    cfg.org.organization_id = "custom_test"
    cfg.org.company_profile = "custom"
    handler = WSHandler.__new__(WSHandler)
    handler.engine = SimpleNamespace(config=cfg, org_engine=OrgEngine(cfg))
    handler._clients = set()
    handler._shutting_down = False
    handler._ws_is_open = lambda _ws: True
    handler._exec_mode = "org"
    handler._company_profile = "custom"
    handler._config_lock = AsyncMock()
    handler._config_lock.__aenter__ = AsyncMock(return_value=None)
    handler._config_lock.__aexit__ = AsyncMock(return_value=None)
    handler._broadcast_org_info = AsyncMock()
    handler._persist_runtime_config = MagicMock()
    return handler


class UnassignEmployeeHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unassign_secondary_role_keeps_employee(self) -> None:
        cfg = OPCConfig()
        cfg.org.roles = [
            RoleConfig(id="student", name="Student", responsibility="Learn.", reports_to="owner"),
            RoleConfig(id="mentor", name="Mentor", responsibility="Teach.", reports_to="owner"),
        ]
        cfg.org.employees = [
            EmployeeConfig(
                employee_id="emp1",
                name="Alex",
                role_id="student",
                metadata={"staffed_role_ids": ["mentor"]},
            )
        ]
        handler = _make_handler(cfg)
        ws = AsyncMock()
        with patch.object(OPCConfig, "save", autospec=True):
            await handler._handle_unassign_employee(ws, {"role_id": "mentor", "employee_id": "emp1"})

        self.assertEqual(len(cfg.org.employees), 1)
        self.assertEqual(cfg.org.employees[0].role_id, "student")
        self.assertNotIn("mentor", cfg.org.employees[0].metadata.get("staffed_role_ids", []))
        payload = ws.send_json.call_args.args[0]
        self.assertTrue(payload["payload"]["ok"])

    async def test_unassign_only_role_removes_employee(self) -> None:
        cfg = OPCConfig()
        cfg.org.roles = [
            RoleConfig(id="student", name="Student", responsibility="Learn.", reports_to="owner"),
        ]
        cfg.org.employees = [
            EmployeeConfig(employee_id="emp1", name="Alex", role_id="student"),
        ]
        handler = _make_handler(cfg)
        ws = AsyncMock()
        with patch.object(OPCConfig, "save", autospec=True):
            await handler._handle_unassign_employee(ws, {"role_id": "student", "employee_id": "emp1"})

        self.assertFalse(any(e.employee_id == "emp1" for e in cfg.org.employees))

    async def test_unassign_requires_role_and_employee_id(self) -> None:
        cfg = OPCConfig()
        handler = _make_handler(cfg)
        ws = AsyncMock()
        await handler._handle_unassign_employee(ws, {"role_id": "student"})
        payload = ws.send_json.call_args.args[0]
        self.assertFalse(payload["payload"]["ok"])
