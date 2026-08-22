"""
LogStore — lightweight persistent log storage for FreqBridge.

Uses SQLite (Python stdlib, zero extra dependency) so simulation logs
survive a `/reset` and even a full backend restart, instead of living
only in the runner's in-memory list.

Design goal: logging must NEVER be able to crash the simulation loop.
Every DB operation is wrapped in try/except and degrades to a silent
no-op (falling back to in-memory-only behavior) if the database can't
be opened or written to — e.g. disk full, permissions issue, locked
file. Reads similarly return an empty result rather than raising.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs.sqlite3")


class LogStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._available = True
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._init_schema()
        except Exception as e:
            self._available = False
            print(
                f"[LogStore] WARNING: could not initialize log database "
                f"({e}). Logs will not be persisted this session — the "
                f"live in-memory log panel will still work normally."
            )

    def is_available(self) -> bool:
        return self._available

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5.0)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    tick INTEGER,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def start_session(self) -> int:
        """
        Record a new session boundary and return its id. This is purely
        for grouping/inspection later — it does NOT create a gap or reset
        in the `logs` table's row numbering. Falls back to 0 (still usable
        as a session_id) if the DB is unavailable.
        """
        if not self._available:
            return 0
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO sessions (started_at) VALUES (?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                return cur.lastrowid
        except Exception as e:
            print(f"[LogStore] WARNING: could not start session ({e}).")
            return 0

    def insert(self, session_id: int, tick: Optional[int], message: str) -> None:
        """Persist one log line. Never raises — logging failures must not
        be able to take down the simulation loop."""
        if not self._available:
            return
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO logs (session_id, tick, message, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, tick, message, datetime.now(timezone.utc).isoformat()),
                )
        except Exception as e:
            print(f"[LogStore] WARNING: failed to persist log line ({e}).")

    def get_all(self, limit: Optional[int] = None) -> List[Dict]:
        """Full persisted history, oldest first. Returns [] (never raises)
        if the DB is unavailable or the read fails."""
        if not self._available:
            return []
        try:
            with self._connect() as conn:
                query = (
                    "SELECT id, session_id, tick, message, created_at "
                    "FROM logs ORDER BY id ASC"
                )
                if limit:
                    query += f" LIMIT {int(limit)}"
                rows = conn.execute(query).fetchall()
            return [
                {
                    "id": r[0],
                    "session_id": r[1],
                    "tick": r[2],
                    "message": r[3],
                    "created_at": r[4],
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[LogStore] WARNING: failed to read log history ({e}).")
            return []

    def last_id(self) -> int:
        """Highest log row id ever stored, or 0 if none / unavailable.
        Used to prove log continuity is unbroken across resets."""
        if not self._available:
            return 0
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT MAX(id) FROM logs").fetchone()
            return row[0] or 0
        except Exception:
            return 0