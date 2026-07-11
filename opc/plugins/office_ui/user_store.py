"""SQLite-backed store for user accounts, invite codes, and session tokens.

Mirrors the AgentStore/ChatStore pattern: the connection is opened once by
the caller (server.py or a CLI command) and shared; initialize() only ever
CREATEs, never migrates existing installs (there are none yet).
"""

from __future__ import annotations

import hashlib
import secrets
import time

import aiosqlite


def _hash_invite_code(invite_code: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", invite_code.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return digest.hex()


class UserStore:
    """Persists users, invite codes, and session tokens in ui_state.db."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def initialize(self) -> None:
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS invite_codes (
                code TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'unused',
                used_by_user_id TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.commit()

    async def create_invite_code(self, code: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO invite_codes (code, status, created_at) VALUES (?, 'unused', ?)",
            (code, time.time()),
        )
        await self._db.commit()

    async def register(self, username: str, invite_code: str) -> tuple[str | None, str | None]:
        """Create a user account. Returns (user_id, None) or (None, error_code)."""
        cursor = await self._db.execute(
            "SELECT status FROM invite_codes WHERE code = ?", (invite_code,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None, "invite_code_invalid"
        if row[0] != "unused":
            return None, "invite_code_used"

        cursor = await self._db.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if await cursor.fetchone() is not None:
            return None, "username_taken"

        user_id = secrets.token_hex(16)
        salt = secrets.token_hex(16)
        password_hash = _hash_invite_code(invite_code, salt)
        await self._db.execute(
            "INSERT INTO users (user_id, username, password_salt, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, salt, password_hash, time.time()),
        )
        await self._db.execute(
            "UPDATE invite_codes SET status = 'used', used_by_user_id = ? WHERE code = ?",
            (user_id, invite_code),
        )
        await self._db.commit()
        return user_id, None

    async def authenticate(self, username: str, invite_code: str) -> str | None:
        """Verify username + invite_code. Returns user_id on success, None on failure."""
        cursor = await self._db.execute(
            "SELECT user_id, password_salt, password_hash FROM users WHERE username = ?",
            (username,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        user_id, salt, expected_hash = row
        if _hash_invite_code(invite_code, salt) != expected_hash:
            return None
        return user_id

    async def create_session(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        await self._db.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user_id, time.time()),
        )
        await self._db.commit()
        return token

    async def get_user_id_for_token(self, token: str) -> str | None:
        cursor = await self._db.execute("SELECT user_id FROM sessions WHERE token = ?", (token,))
        row = await cursor.fetchone()
        return row[0] if row else None
