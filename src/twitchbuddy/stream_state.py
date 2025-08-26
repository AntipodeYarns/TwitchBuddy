from __future__ import annotations

import threading
from typing import Dict


class StreamState:
    """Thread-safe in-memory stream state tracker for testing and runtime.

    Use `set_online(channel, True/False)` to mark a channel online/offline and
    `is_online(channel)` to query. This is intentionally simple and in-memory;
    production code should replace with a real health check if needed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[str, bool] = {}

    def set_online(self, channel: str, online: bool) -> None:
        with self._lock:
            self._state[channel] = bool(online)

    def is_online(self, channel: str) -> bool:
        with self._lock:
            return bool(self._state.get(channel, False))


# module-level singleton for easy access
_GLOBAL = StreamState()


def set_stream_online(channel: str, online: bool) -> None:
    _GLOBAL.set_online(channel, online)


def is_stream_online(channel: str) -> bool:
    return _GLOBAL.is_online(channel)
