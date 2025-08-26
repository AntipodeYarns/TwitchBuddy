"""ClickHouse logging helper for TwitchBuddy.

Provides an optional, dependency-light wrapper that sends chat/mod/trigger
events to ClickHouse. If `clickhouse_driver` is unavailable or CH endpoint is
not configured, this module becomes a no-op logger so it won't break tests.

Usage:
  from twitchbuddy.ch_logging import get_logger
  logger = get_logger()
  logger.log_chat(username, fired, name, ts)

Configuration via env:
  CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DB

Also provides `CLICKHOUSE_DDL` for creating the recommended table.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Dict, Optional, Callable
import threading
import queue
import time

try:
    from clickhouse_driver import Client as CHClient
except Exception:  # pragma: no cover - optional dependency
    CHClient = None


CLICKHOUSE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS twitch_logs (
        ts DateTime64(3),
        event_type String,
        channel String,
        user String,
        triggered UInt8,
        name Nullable(String),
        details String
    )
    ENGINE = MergeTree()
    PARTITION BY toYYYYMMDD(ts)
    ORDER BY (channel, ts)
    TTL ts + INTERVAL 90 DAY
    """
]


@dataclass
class ClickHouseLogger:
    client: Any | None
    database: Optional[str] = None

    def _insert(self, row: Dict[str, Any]) -> None:
        if not self.client:
            return
        try:
            self.client.execute(
                "INSERT INTO twitch_logs (ts, event_type, channel, user, triggered, name, details) VALUES",
                [
                    (
                        row.get("ts"),
                        row.get("event_type"),
                        row.get("channel"),
                        row.get("user"),
                        int(bool(row.get("triggered"))),
                        row.get("name"),
                        json.dumps(row.get("details") or {}),
                    )
                ],
            )
        except Exception:
            # never let logging break the app; best-effort
            return

    def log_chat(
        self,
        channel: str,
        username: str,
        fired: bool,
        name: Optional[str],
        ts: Optional[datetime] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = {
            "ts": ts or datetime.now(UTC),
            "event_type": "chat_message",
            "channel": channel,
            "user": username,
            "triggered": fired,
            "name": name,
            "details": extra or {},
        }
        self._insert(row)

    def log_mod_action(
        self,
        channel: str,
        target_user: str,
        action: str,
        args: Optional[Dict[str, Any]] = None,
        ts: Optional[datetime] = None,
    ) -> None:
        row = {
            "ts": ts or datetime.now(UTC),
            "event_type": "mod_action",
            "channel": channel,
            "user": target_user,
            "triggered": False,
            "name": action,
            "details": args or {},
        }
        self._insert(row)

    def log_trigger_event(
        self,
        channel: str,
        trigger_name: str,
        trigger_type: str,
        ts: Optional[datetime] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = {
            "ts": ts or datetime.now(UTC),
            "event_type": "trigger_event",
            "channel": channel,
            "user": "",
            "triggered": True,
            "name": trigger_name,
            "details": {"trigger_type": trigger_type, **(extra or {})},
        }
        self._insert(row)


def get_logger() -> ClickHouseLogger:
    """Return a ClickHouseLogger bound to configured host if available.

    If clickhouse driver or environment is not present, return a no-op logger.
    """
    host = os.environ.get("CLICKHOUSE_HOST")
    if not host or CHClient is None:
        # No ClickHouse configured or driver missing: return noop logger
        return ClickHouseLogger(client=None)

    port = int(os.environ.get("CLICKHOUSE_PORT", "9000"))
    user = os.environ.get("CLICKHOUSE_USER") or "default"
    password = os.environ.get("CLICKHOUSE_PASSWORD")
    database = os.environ.get("CLICKHOUSE_DB")

    # create client and return a batched logger
    try:
        client = CHClient(
            host=host, port=port, user=user, password=password, database=database
        )
        # optional: ensure DB exists
        if database:
            try:
                client.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
            except Exception:
                pass
        return BatchedClickHouseLogger(client=client, database=database)
    except Exception:
        return ClickHouseLogger(client=None)


class BatchedClickHouseLogger(ClickHouseLogger):
    """Logger that batches inserts to ClickHouse.

    Flush policy: flush when buffer reaches `batch_size` or when the
    oldest record has been buffered for `batch_time` seconds.
    """

    # annotated so static checkers know this attribute exists and its type
    _stream_check: Optional[Callable[[], bool]]

    def __init__(
        self,
        client: Any,
        database: Optional[str] = None,
        batch_size: int = 50,
        batch_time: int = 15 * 60,
        stream_check: Optional[Callable[[], bool]] = None,
        grace_period: int | None = None,
        poll_interval: int = 60,
    ) -> None:
        super().__init__(client=client, database=database)
        self.batch_size = int(batch_size)
        self.batch_time = int(batch_time)
        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._stop = threading.Event()
        # optional callable to check whether the stream is online.
        # If provided and the stream is offline at close time, the
        # logger will continue to persist for `grace_period` seconds
        # (default 15 minutes) while polling `stream_check` every
        # `poll_interval` seconds.
        self._stream_check = stream_check
        self._grace_period = int(grace_period) if grace_period is not None else 15 * 60
        self._poll_interval = int(poll_interval)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        buf: list[Dict[str, Any]] = []
        first_ts: Optional[float] = None
        while not self._stop.is_set():
            try:
                # compute timeout based on first_ts; cap to 1s so we remain responsive
                if first_ts is None:
                    timeout = 1.0
                else:
                    elapsed = time.time() - first_ts
                    remaining = max(0, self.batch_time - int(elapsed))
                    # use a short wake-up interval to allow timely shutdown
                    timeout = min(1.0, remaining) if remaining > 0 else 0
                item = self._q.get(timeout=timeout)
                buf.append(item)
                if first_ts is None:
                    first_ts = time.time()
                # flush if batch size reached
                if len(buf) >= self.batch_size:
                    self._flush(buf)
                    buf = []
                    first_ts = None
            except Exception:
                # queue.Empty or other; on timeout flush if buffer has data
                if buf:
                    self._flush(buf)
                    buf = []
                    first_ts = None
                # brief sleep to avoid tight loop
                time.sleep(0.1)
        # drain remaining
        while True:
            try:
                item = self._q.get_nowait()
                buf.append(item)
            except Exception:
                break
        if buf:
            self._flush(buf)

    def _flush(self, buf: list[Dict[str, Any]]) -> None:
        if not self.client:
            return
        try:
            rows = [
                (
                    item.get("ts"),
                    item.get("event_type"),
                    item.get("channel"),
                    item.get("user"),
                    int(bool(item.get("triggered"))),
                    item.get("name"),
                    json.dumps(item.get("details") or {}),
                )
                for item in buf
            ]
            # execute batched insert
            self.client.execute(
                "INSERT INTO twitch_logs (ts, event_type, channel, user, triggered, name, details) VALUES",
                rows,
            )
        except Exception:
            # swallow errors
            return

    def _insert(self, row: Dict[str, Any]) -> None:
        # push to queue for background flush
        try:
            self._q.put_nowait(row)
        except Exception:
            pass

    def close(self, timeout: Optional[float] = None) -> None:
        """Stop the background worker.

        If a `stream_check` callable was provided and it reports the
        stream is offline, the logger will continue running and
        flushing for up to `self._grace_period` seconds, polling
        every `self._poll_interval` seconds for the stream to
        return online. If the stream becomes online during this
        window, the logger will then stop. If no `stream_check` is
        configured, behaves like the previous implementation.
        """

        # If no stream check provided, stop immediately
        if self._stream_check is None:
            self._stop.set()
            self._thread.join(timeout=timeout)
            return

        try:
            # If stream currently online, stop immediately
            if self._stream_check():
                self._stop.set()
                self._thread.join(timeout=timeout)
                return
        except Exception:
            # On any error while checking, proceed to immediate stop
            self._stop.set()
            self._thread.join(timeout=timeout)
            return

        # Stream is offline: keep persisting for up to grace_period
        import time

        deadline = time.time() + int(self._grace_period)
        while time.time() < deadline:
            # if stream comes back online, stop early
            try:
                if self._stream_check():
                    break
            except Exception:
                # on error, continue polling until deadline
                pass
            # sleep in poll intervals but respect overall timeout
            step = min(self._poll_interval, max(0, deadline - time.time()))
            if step <= 0:
                break
            time.sleep(step)

        # finally stop and join
        self._stop.set()
        self._thread.join(timeout=timeout)
