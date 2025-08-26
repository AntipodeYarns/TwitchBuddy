from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from .paths import default_db_path
from typing import List, Optional


@dataclass
class StoredAsset:
    id: str
    short_name: str
    asset_kind: str  # 'audio' or 'visual'
    asset_class: str
    file_path: str
    file_type: Optional[str]
    loopable: str  # 'yes' or 'no'
    media_length: Optional[str]
    copyright_safe: str  # 'yes' or 'no'
    created_at: Optional[str] = None


class AssetStore:
    """SQLite-backed store for audio/visual assets.

    Fields per asset:
      id TEXT PRIMARY KEY,
      short_name TEXT UNIQUE,
      asset_kind TEXT NOT NULL CHECK(asset_kind IN ('audio','visual')),
      file_path TEXT NOT NULL,
      file_type TEXT,
      loopable TEXT CHECK(loopable IN ('yes','no')) DEFAULT 'no',
      media_length TEXT,
      copyright_safe TEXT CHECK(copyright_safe IN ('yes','no')) DEFAULT 'no',
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        # use a single consolidated DB file by default
        if db_path is None:
            self._db_path = default_db_path("TwitchBuddy.db")
        else:
            self._db_path = Path(db_path)
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
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    short_name TEXT UNIQUE NOT NULL,
                    asset_kind TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_type TEXT,
                    loopable TEXT DEFAULT 'no',
                    media_length TEXT,
                    copyright_safe TEXT DEFAULT 'no',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def add_asset(
        self,
        short_name: str,
        asset_kind: str,
        file_path: str,
        file_type: Optional[str] = None,
        loopable: str = "no",
        media_length: Optional[str] = None,
        copyright_safe: str = "no",
        asset_class: Optional[str] = None,
    ) -> str:
        if asset_kind not in ("audio", "visual"):
            raise ValueError("asset_kind must be 'audio' or 'visual'")
        if loopable not in ("yes", "no"):
            raise ValueError("loopable must be 'yes' or 'no'")
        if copyright_safe not in ("yes", "no"):
            raise ValueError("copyright_safe must be 'yes' or 'no'")

        # default asset_class to asset_kind if not provided
        if asset_class is None:
            asset_class = asset_kind
        if asset_class not in ("audio", "visual"):
            raise ValueError("asset_class must be 'audio' or 'visual'")

        aid = str(uuid.uuid4())
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO assets (id, short_name, asset_kind, asset_class, file_path, file_type, loopable, media_length, copyright_safe) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid,
                    short_name,
                    asset_kind,
                    asset_class,
                    file_path,
                    file_type,
                    loopable,
                    media_length,
                    copyright_safe,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return aid

    def remove_asset(self, identifier: str) -> bool:
        """Remove by id or short_name."""
        conn = self._get_conn()
        try:
            # try by id first
            cur = conn.execute("DELETE FROM assets WHERE id = ?", (identifier,))
            if cur.rowcount == 0:
                cur = conn.execute(
                    "DELETE FROM assets WHERE short_name = ?", (identifier,)
                )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_assets(self, kind: Optional[str] = None) -> List[StoredAsset]:
        conn = self._get_conn()
        try:
            if kind:
                cur = conn.execute(
                    "SELECT id, short_name, asset_kind, asset_class, file_path, file_type, loopable, media_length, copyright_safe, created_at FROM assets WHERE asset_kind = ?",
                    (kind,),
                )
            else:
                cur = conn.execute(
                    "SELECT id, short_name, asset_kind, asset_class, file_path, file_type, loopable, media_length, copyright_safe, created_at FROM assets"
                )
            rows = cur.fetchall()
            out: List[StoredAsset] = []
            for r in rows:
                out.append(
                    StoredAsset(
                        id=r["id"],
                        short_name=r["short_name"],
                        asset_kind=r["asset_kind"],
                        asset_class=r["asset_class"],
                        file_path=r["file_path"],
                        file_type=r["file_type"],
                        loopable=r["loopable"],
                        media_length=r["media_length"],
                        copyright_safe=r["copyright_safe"],
                        created_at=r["created_at"],
                    )
                )
            return out
        finally:
            conn.close()

    def get_asset_by_short_name(self, short_name: str) -> Optional[StoredAsset]:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT id, short_name, asset_kind, asset_class, file_path, file_type, loopable, media_length, copyright_safe, created_at FROM assets WHERE short_name = ?",
                (short_name,),
            )
            r = cur.fetchone()
            if not r:
                return None
            return StoredAsset(
                id=r["id"],
                short_name=r["short_name"],
                asset_kind=r["asset_kind"],
                asset_class=r["asset_class"],
                file_path=r["file_path"],
                file_type=r["file_type"],
                loopable=r["loopable"],
                media_length=r["media_length"],
                copyright_safe=r["copyright_safe"],
                created_at=r["created_at"],
            )
        finally:
            conn.close()
