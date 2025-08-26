from __future__ import annotations

import asyncio
import json
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
    """Simple interval-based scheduler with JSON persistence.

    Schedules are stored as a list of dicts at the provided path. Each schedule is
    an interval in seconds and a message to send. The scheduler calls the
    provided send_callable(message) asynchronously on each firing.
    """

    def __init__(
        self,
        send_callable: Callable[[str], Awaitable[None]],
        persist_path: Optional[Path] = None,
    ) -> None:
        self._send = send_callable
        self._persist_path = persist_path or Path.cwd() / "schedules.json"
        self._schedules: Dict[str, Schedule] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def load(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for item in raw:
                s = Schedule(**item)
                self._schedules[s.id] = s
        except Exception:
            # ignore malformed persist file
            return

    def save(self) -> None:
        arr = [asdict(s) for s in self._schedules.values()]
        self._persist_path.write_text(json.dumps(arr, indent=2), encoding="utf-8")

    def list(self) -> Dict[str, Dict[str, Any]]:
        return {sid: asdict(s) for sid, s in self._schedules.items()}

    def add(self, message: str, interval_seconds: int, enabled: bool = True) -> str:
        sid = str(uuid.uuid4())
        s = Schedule(
            id=sid, message=message, interval_seconds=interval_seconds, enabled=enabled
        )
        self._schedules[sid] = s
        self.save()
        return sid

    def remove(self, schedule_id: str) -> bool:
        if schedule_id in self._schedules:
            self._schedules.pop(schedule_id)
            # cancel task if running
            t = self._tasks.pop(schedule_id, None)
            if t:
                t.cancel()
            self.save()
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
