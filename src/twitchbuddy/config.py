from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    """Centralized runtime configuration for TwitchBuddy.

    - db_path: Optional path to the SQLite DB file. If None, stores use the
      OS-appropriate default.
    """

    db_path: Optional[Path] = None

    @classmethod
    def from_env(cls) -> "Config":
        import os

        db = os.environ.get("TWITCHBUDDY_DB_PATH")
        return cls(db_path=Path(db) if db else None)
