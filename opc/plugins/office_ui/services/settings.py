"""Global LLM model / API key settings, shared by Office UI."""

from __future__ import annotations

from typing import Any

from .context import OfficeServiceContext
from .models import ServiceResult


class SettingsService:
    def __init__(self, context: OfficeServiceContext) -> None:
        self.context = context

    async def get_llm_config(self) -> ServiceResult:
        llm = self.context.engine.config.llm
        return ServiceResult({
            "default_model": llm.default_model,
            "api_base": llm.api_base,
            "api_key_set": bool(llm.api_key),
        })

    async def update_llm_config(self, patch: dict[str, Any]) -> ServiceResult:
        async with self.context.config_lock:
            llm = self.context.engine.config.llm
            new_model = str(patch.get("default_model") or "").strip()
            if new_model:
                llm.default_model = new_model
            if "api_base" in patch:
                llm.api_base = str(patch.get("api_base") or "").strip()
            new_key = str(patch.get("api_key") or "").strip()
            if new_key:
                llm.api_key = new_key
            if self.context.persist_runtime_config is not None:
                self.context.persist_runtime_config()
            else:
                self.context.engine.config.save()
            self.context.rebind_config(self.context.engine.config)
        return await self.get_llm_config()
