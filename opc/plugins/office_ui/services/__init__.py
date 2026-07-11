"""Shared Office services used by WebSocket UI, CLI, and CLI board."""

from __future__ import annotations

from .agent import AgentService
from .comms import CommsService
from .connectors import ConnectorsService
from .context import ModeState, OfficeServiceContext
from .kanban import KanbanService
from .market import MarketService
from .models import ServiceError, ServiceEvent, ServiceResult
from .nodes import NodesService
from .org import OrgService
from .project import ProjectService
from .runtime import RuntimeService
from .session import SessionService
from .settings import SettingsService
from .talent import TalentService
from .work_item import WorkItemService


class OfficeServices:
    def __init__(self, context: OfficeServiceContext) -> None:
        self.context = context
        self.settings = SettingsService(context)
        self.project = ProjectService(context)
        self.session = SessionService(context)
        self.kanban = KanbanService(context, self.session)
        self.runtime = RuntimeService(context, self.session)
        self.agent = AgentService(context)
        self.org = OrgService(context)
        self.talent = TalentService(context)
        self.market = MarketService(context)
        self.nodes = NodesService()
        self.comms = CommsService(context)
        self.work_item = WorkItemService(context)
        self.connectors = ConnectorsService(context)


__all__ = [
    "AgentService",
    "CommsService",
    "ConnectorsService",
    "KanbanService",
    "MarketService",
    "ModeState",
    "NodesService",
    "OfficeServiceContext",
    "OfficeServices",
    "OrgService",
    "ProjectService",
    "RuntimeService",
    "ServiceError",
    "ServiceEvent",
    "ServiceResult",
    "SessionService",
    "SettingsService",
    "TalentService",
    "WorkItemService",
]
