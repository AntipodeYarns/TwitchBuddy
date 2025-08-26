from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from .paths import default_db_path
from typing import Dict, Any, List, Optional
import threading
from typing import Callable
import time


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


# Simple in-process cache to avoid hitting the DB on every chat message.
# Provides listener registration so consumers (e.g. ChatClient) can be
# notified when triggers refresh.
class TriggerCache:
    def __init__(self, store: TriggerStore):
        self._store = store
        self._lock = threading.Lock()
        self._cached: List[StoredTrigger] = []
        self._listeners: List[Callable[[List[StoredTrigger]], None]] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def refresh(self) -> None:
        with self._lock:
            self._cached = self._store.list_triggers()
            snapshot = list(self._cached)
        # notify listeners outside lock
        for listener in list(self._listeners):
            try:
                listener(snapshot)
            except Exception:
                # listener errors shouldn't break cache
                continue

    def list_cached_triggers(self) -> List[StoredTrigger]:
        with self._lock:
            return list(self._cached)

    def register_listener(
        self, listener: Callable[[List[StoredTrigger]], None]
    ) -> None:
        with self._lock:
            self._listeners.append(listener)

    def unregister_listener(
        self, listener: Callable[[List[StoredTrigger]], None]
    ) -> None:
        with self._lock:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

    def notify_change(self) -> None:
        """Called when DB writes occur (add/update/delete). Refresh immediately."""
        try:
            self.refresh()
        except Exception:
            pass

    def start_auto_refresh(
        self,
        stream_check: Optional[Callable[[], bool]] = None,
        refresh_interval: int = 1800,
    ) -> None:
        """Start a background thread that refreshes cache every `refresh_interval` seconds
        while `stream_check()` returns True. If `stream_check` is None, always refresh on interval.
        When starting, refresh immediately if stream_check reports True (or no stream_check supplied).
        """

        def _run():
            # immediate refresh if appropriate
            try:
                if stream_check is None or stream_check():
                    self.refresh()
            except Exception:
                # ignore stream_check errors
                self.refresh()

            while not self._stop.is_set():
                try:
                    # only refresh if stream is online (or no check provided)
                    if stream_check is None or stream_check():
                        self.refresh()
                except Exception:
                    # swallow errors and continue
                    pass
                # sleep in small increments so thread can be stopped quickly
                total = 0
                while total < refresh_interval and not self._stop.is_set():
                    time.sleep(1)
                    total += 1

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop_auto_refresh(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass


# Module-level cache registry keyed by db_path string
_CACHES: Dict[str, TriggerCache] = {}


def get_trigger_cache(db_path: Optional[Path] = None) -> TriggerCache:
    key = (
        str(db_path) if db_path is not None else str(default_db_path("TwitchBuddy.db"))
    )
    if key in _CACHES:
        return _CACHES[key]
    store = TriggerStore(db_path=Path(db_path) if db_path is not None else None)
    cache = TriggerCache(store)
    # perform an initial refresh
    try:
        cache.refresh()
    except Exception:
        pass
    _CACHES[key] = cache
    return cache
