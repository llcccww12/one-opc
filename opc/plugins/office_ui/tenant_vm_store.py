"""SQLite-backed store for per-user SkyPilot VM lifecycle state.

Mirrors the UserStore/AgentStore pattern: the connection is opened once by
the caller (server.py) and shared; initialize() only ever CREATEs. One VM
per user — user_id is the primary key.
"""

from __future__ import annotations

import asyncio
import time

import aiosqlite


class TenantVmStore:
    """Persists one SkyPilot VM record per user in ui_state.db."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_vms (
                user_id TEXT PRIMARY KEY,
                cluster_name TEXT NOT NULL,
                status TEXT NOT NULL,
                auth_token TEXT,
                error_message TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        await self._db.commit()

    async def get_vm(self, user_id: str) -> dict | None:
        cursor = await self._db.execute(
            "SELECT cluster_name, status, auth_token, error_message, created_at, updated_at "
            "FROM tenant_vms WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "cluster_name": row[0],
            "status": row[1],
            "auth_token": row[2],
            "error_message": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }

    async def create_vm(self, user_id: str, cluster_name: str, auth_token: str) -> None:
        async with self._write_lock:
            now = time.time()
            await self._db.execute(
                "INSERT INTO tenant_vms "
                "(user_id, cluster_name, status, auth_token, error_message, created_at, updated_at) "
                "VALUES (?, ?, 'launching', ?, NULL, ?, ?)",
                (user_id, cluster_name, auth_token, now, now),
            )
            await self._db.commit()

    async def update_status(self, user_id: str, status: str, error_message: str | None = None) -> None:
        async with self._write_lock:
            await self._db.execute(
                "UPDATE tenant_vms SET status = ?, error_message = ?, updated_at = ? WHERE user_id = ?",
                (status, error_message, time.time(), user_id),
            )
            await self._db.commit()

    async def reset_stale_launching(self) -> int:
        """Mark any rows stuck in 'launching' (e.g. left behind by a server
        restart/crash with no live task) as 'error' so bind() can retry them."""
        async with self._write_lock:
            cursor = await self._db.execute(
                "UPDATE tenant_vms SET status = 'error', error_message = ?, updated_at = ? "
                "WHERE status = 'launching'",
                ("服务重启，请重试", time.time()),
            )
            await self._db.commit()
            return cursor.rowcount
