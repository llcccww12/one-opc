"""Per-user encrypted BYOK model-credential storage.

Scoped to the worker/VM dispatch path only (the external claude_code agent
running on a user's own SkyPilot VM) — the native-agent LLM path stays on
the existing global LLMConfig/SettingsService and is out of scope here;
threading user_id through it touches ~100 call sites across 15 files and
is a separate initiative.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import aiosqlite
from cryptography.fernet import Fernet


def _load_or_create_key(key_path: Path) -> bytes:
    if key_path.exists():
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # best-effort; e.g. a no-op on Windows
    return key


class CredentialVault:
    """Persists one BYOK (api_key, api_base) pair per user in ui_state.db."""

    def __init__(self, db: aiosqlite.Connection, key_path: Path) -> None:
        self._db = db
        self._fernet = Fernet(_load_or_create_key(key_path))
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id TEXT PRIMARY KEY,
                api_key_encrypted TEXT NOT NULL,
                api_base TEXT,
                updated_at REAL NOT NULL
            )
            """
        )
        await self._db.commit()

    async def get_credentials(self, user_id: str) -> tuple[str, str] | None:
        cursor = await self._db.execute(
            "SELECT api_key_encrypted, api_base FROM user_credentials WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        api_key = self._fernet.decrypt(row[0].encode("utf-8")).decode("utf-8")
        return api_key, row[1] or ""

    async def has_credentials(self, user_id: str) -> bool:
        return await self.get_credentials(user_id) is not None

    async def set_credentials(self, user_id: str, api_key: str, api_base: str = "") -> None:
        encrypted = self._fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")
        async with self._write_lock:
            now = time.time()
            await self._db.execute(
                "INSERT INTO user_credentials (user_id, api_key_encrypted, api_base, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "api_key_encrypted = excluded.api_key_encrypted, "
                "api_base = excluded.api_base, "
                "updated_at = excluded.updated_at",
                (user_id, encrypted, api_base, now),
            )
            await self._db.commit()
