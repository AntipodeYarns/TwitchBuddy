from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from .paths import default_db_path
from typing import Dict, Any, List, Optional


@dataclass
class StoredTrigger:
    id: str
    regex_pattern: str
    response_type_id: int
    response_text: Optional[str]
    arg_mappings: Optional[Dict[str, Any]]
    cooldown_minutes: int = 0
    last_fired: float = 0.0


class TriggerStore:
    """Simple SQLite-backed storage for text triggers.

    Schema:
      response_type(id INTEGER PRIMARY KEY, response_type TEXT)
      triggers(id TEXT PRIMARY KEY, regex_pattern TEXT, response_type_id INTEGER,
               response_text TEXT NULL, arg_mappings TEXT NULL, cooldown_minutes INTEGER DEFAULT 0)

    The store seeds `response_type` with (1, 'chat_message') and (2, 'alert').
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the TriggerStore.

        Uses an OS-appropriate default data directory when no explicit
        db_path is provided.
        """
        # default to a single consolidated DB file inside the OS-appropriate data dir
        self._db_path = (
            Path(db_path) if db_path is not None else default_db_path("TwitchBuddy.db")
        )
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS response_type (
                    id INTEGER PRIMARY KEY,
                    response_type TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS triggers (
                    id TEXT PRIMARY KEY,
                    regex_pattern TEXT NOT NULL,
                    response_type_id INTEGER NOT NULL,
                    response_text TEXT,
                    arg_mappings TEXT,
                    cooldown_minutes INTEGER DEFAULT 0,
                    last_fired REAL DEFAULT 0,
                    FOREIGN KEY(response_type_id) REFERENCES response_type(id)
                )
                """
            )
            # seed response types if missing
            cur = conn.execute("SELECT COUNT(*) as c FROM response_type")
            row = cur.fetchone()
            if row and row["c"] == 0:
                conn.executemany(
                    "INSERT INTO response_type (id, response_type) VALUES (?, ?)",
                    [(1, "chat_message"), (2, "alert")],
                )
            conn.commit()
        finally:
            conn.close()

        # If an existing DB was created without last_fired, add the column.
        # ALTER TABLE ADD COLUMN is safe if column is missing; ignore otherwise.
        conn2 = self._get_conn()
        try:
            cur = conn2.execute("PRAGMA table_info(triggers)")
            cols = [r[1] for r in cur.fetchall()]
            if "last_fired" not in cols:
                try:
                    conn2.execute(
                        "ALTER TABLE triggers ADD COLUMN last_fired REAL DEFAULT 0"
                    )
                    conn2.commit()
                except Exception:
                    # best-effort migration; if it fails, continue without raising
                    pass
        finally:
            conn2.close()

    def add_trigger(
        self,
        regex_pattern: str,
        response_type_id: int,
        response_text: Optional[str] = None,
        arg_mappings: Optional[Dict[str, Any]] = None,
        cooldown_minutes: int = 0,
    ) -> str:
        tid = str(uuid.uuid4())
        arg_json = json.dumps(arg_mappings) if arg_mappings is not None else None
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO triggers (id, regex_pattern, response_type_id, response_text, arg_mappings, cooldown_minutes, last_fired) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    tid,
                    regex_pattern,
                    int(response_type_id),
                    response_text,
                    arg_json,
                    int(cooldown_minutes),
                    0.0,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return tid

    def update_last_fired(self, trigger_id: str, ts: float) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE triggers SET last_fired = ? WHERE id = ?",
                (float(ts), trigger_id),
            )
            conn.commit()
        finally:
            conn.close()

    def remove_trigger(self, trigger_id: str) -> bool:
        conn = self._get_conn()
        try:
            cur = conn.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_triggers(self) -> List[StoredTrigger]:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT id, regex_pattern, response_type_id, response_text, arg_mappings, cooldown_minutes, last_fired FROM triggers"
            )
            rows = cur.fetchall()
            out: List[StoredTrigger] = []
            for r in rows:
                arg_mappings = None
                if r["arg_mappings"]:
                    try:
                        arg_mappings = json.loads(r["arg_mappings"])
                    except Exception:
                        arg_mappings = None
                out.append(
                    StoredTrigger(
                        id=r["id"],
                        regex_pattern=r["regex_pattern"],
                        response_type_id=int(r["response_type_id"]),
                        response_text=r["response_text"],
                        arg_mappings=arg_mappings,
                        cooldown_minutes=int(r["cooldown_minutes"] or 0),
                        last_fired=float(r["last_fired"] or 0.0),
                    )
                )
            return out
        finally:
            conn.close()
