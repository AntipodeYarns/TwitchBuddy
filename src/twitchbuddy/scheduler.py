from __future__ import annotations

import asyncio
import sqlite3
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Awaitable, Dict, Any, Optional


@dataclass
class Schedule:
    id: str
    message: str
    interval_seconds: int
    enabled: bool = True


class Scheduler:
    """Simple interval-based scheduler with SQLite persistence.

    Schedules are stored in a local SQLite database at `db_path` (default
    'schedules.db'). The scheduler will call the provided async `send_callable`
    with the message string on each interval. Database operations are simple
    and lightweight; we create a connection per operation.
    """

    def __init__(
        self,
        send_callable: Callable[[str], Awaitable[None]],
        db_path: Optional[Path] = None,
    ) -> None:
        self._send = send_callable
        self._db_path = db_path or Path.cwd() / "schedules.db"
        self._schedules: Dict[str, Schedule] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        # create a short-lived connection per operation
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    message TEXT NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    enabled INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def load(self) -> None:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT id, message, interval_seconds, enabled FROM schedules"
            )
            rows = cur.fetchall()
            self._schedules = {}
            for r in rows:
                s = Schedule(
                    id=r["id"],
                    message=r["message"],
                    interval_seconds=int(r["interval_seconds"]),
                    enabled=bool(r["enabled"]),
                )
                self._schedules[s.id] = s
        finally:
            conn.close()

    def list(self) -> Dict[str, Dict[str, Any]]:
        # reflect current DB state
        self.load()
        return {sid: asdict(s) for sid, s in self._schedules.items()}

    def add(self, message: str, interval_seconds: int, enabled: bool = True) -> str:
        sid = str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO schedules (id, message, interval_seconds, enabled) VALUES (?, ?, ?, ?)",
                (sid, message, int(interval_seconds), int(bool(enabled))),
            )
            conn.commit()
        finally:
            conn.close()
        # update in-memory and return id
        s = Schedule(
            id=sid, message=message, interval_seconds=interval_seconds, enabled=enabled
        )
        self._schedules[sid] = s
        return sid

    def remove(self, schedule_id: str) -> bool:
        conn = self._get_conn()
        try:
            cur = conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
            conn.commit()
            deleted = cur.rowcount > 0
        finally:
            conn.close()
        if deleted:
            t = self._tasks.pop(schedule_id, None)
            if t:
                t.cancel()
            self._schedules.pop(schedule_id, None)
            return True
        return False

    async def _run_schedule(self, s: Schedule) -> None:
        try:
            while s.enabled:
                await asyncio.sleep(s.interval_seconds)
                try:
                    await self._send(s.message)
                except Exception:
                    # swallow send errors so scheduler keeps running
                    pass
                # refresh enabled flag from DB in case it was toggled externally
                try:
                    conn = self._get_conn()
                    cur = conn.execute(
                        "SELECT enabled FROM schedules WHERE id = ?", (s.id,)
                    )
                    row = cur.fetchone()
                    if row is None:
                        # schedule removed
                        s.enabled = False
                    else:
                        s.enabled = bool(row["enabled"])  # type: ignore[index]
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
        except asyncio.CancelledError:
            return

    def start(self) -> None:
        self.load()
        for sid, s in list(self._schedules.items()):
            if s.enabled and sid not in self._tasks:
                self._tasks[sid] = asyncio.create_task(self._run_schedule(s))

    def stop(self) -> None:
        for t in list(self._tasks.values()):
            t.cancel()
        self._tasks.clear()
