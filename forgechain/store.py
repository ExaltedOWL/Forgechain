"""
SQLite persistence: one chain per session_id (append-only logical log, full snapshot per write).
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from typing import Optional

from .block import ForgeBlock
from .chain import ForgeChain


def _db_path() -> str:
    return os.environ.get("FORGECHAIN_DB", "forgechain.db")


class ChainStore:
    def __init__(self, path: str | None = None):
        self._path = path or _db_path()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS blocks (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    idx INTEGER NOT NULL,
                    block_json TEXT NOT NULL,
                    PRIMARY KEY (session_id, idx)
                );
                """
            )

    def create_session(self) -> tuple[str, str]:
        session_id = secrets.token_hex(12)
        session_key = secrets.token_hex(32)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, session_key) VALUES (?, ?)",
                (session_id, session_key),
            )
        return session_id, session_key

    def get_session_key(self, session_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_key FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row[0] if row else None

    def load_chain(self, session_id: str) -> Optional[tuple[str, list[ForgeBlock]]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT session_key FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            session_key = row[0]
            rows = conn.execute(
                "SELECT block_json FROM blocks WHERE session_id = ? ORDER BY idx",
                (session_id,),
            ).fetchall()
        blocks = [ForgeBlock.model_validate_json(r[0]) for r in rows]
        return session_key, blocks

    def replace_blocks(self, session_id: str, blocks: list[ForgeBlock]) -> None:
        """Full replace of block list for this session (MVP simplicity)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM blocks WHERE session_id = ?", (session_id,))
            for idx, block in enumerate(blocks):
                conn.execute(
                    "INSERT INTO blocks (session_id, idx, block_json) VALUES (?, ?, ?)",
                    (session_id, idx, block.model_dump_json()),
                )
            conn.commit()


_store: ChainStore | None = None


def get_store() -> ChainStore:
    global _store
    if _store is None:
        _store = ChainStore()
        _store.init()
    return _store
