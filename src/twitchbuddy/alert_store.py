from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from .paths import default_db_path
from typing import Any, Dict, List, Optional


@dataclass
class StoredAlert:
    id: str
    alert_name: str
    audio_asset_id: Optional[str]
    visual_asset_id: Optional[str]
    play_duration: Optional[str]
    fade_inout_time: Optional[str]
    text_template: Optional[str]
    arg_mapping: Optional[Dict[str, Any]]
    created_at: Optional[str] = None


class AlertStore:
    """SQLite-backed store for Alerts.

    Alerts reference audio/visual assets by id. Validation ensures referenced
    assets exist and have the expected `asset_class` value ('audio'|'visual').
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        """Initialize the AlertStore.

        Uses an OS-appropriate default data directory when no explicit
        db_path is provided.
        """
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
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    alert_name TEXT NOT NULL,
                    audio_asset_id TEXT,
                    visual_asset_id TEXT,
                    play_duration TEXT,
                    fade_inout_time TEXT,
                    text_template TEXT,
                    arg_mapping TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(audio_asset_id) REFERENCES assets(id),
                    FOREIGN KEY(visual_asset_id) REFERENCES assets(id)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _asset_has_class(self, asset_id: str, expected_class: str) -> bool:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT asset_class FROM assets WHERE id = ?",
                (asset_id,),
            )
            r = cur.fetchone()
            if not r:
                return False
            return (r["asset_class"] or "").lower() == expected_class.lower()
        finally:
            conn.close()

    def add_alert(
        self,
        alert_name: str,
        audio_asset_id: Optional[str] = None,
        visual_asset_id: Optional[str] = None,
        play_duration: Optional[str] = None,
        fade_inout_time: Optional[str] = None,
        text_template: Optional[str] = None,
        arg_mapping: Optional[Dict[str, Any]] = None,
    ) -> str:
        # validate referenced assets if provided
        if audio_asset_id and not self._asset_has_class(audio_asset_id, "audio"):
            raise ValueError("audio_asset_id does not refer to an audio asset")
        if visual_asset_id and not self._asset_has_class(visual_asset_id, "visual"):
            raise ValueError("visual_asset_id does not refer to a visual asset")

        aid = str(uuid.uuid4())
        arg_json = json.dumps(arg_mapping) if arg_mapping is not None else None
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO alerts (id, alert_name, audio_asset_id, visual_asset_id, play_duration, fade_inout_time, text_template, arg_mapping) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid,
                    alert_name,
                    audio_asset_id,
                    visual_asset_id,
                    play_duration,
                    fade_inout_time,
                    text_template,
                    arg_json,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return aid

    def remove_alert(self, alert_id: str) -> bool:
        conn = self._get_conn()
        try:
            cur = conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_alerts(self) -> List[StoredAlert]:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT id, alert_name, audio_asset_id, visual_asset_id, play_duration, fade_inout_time, text_template, arg_mapping, created_at FROM alerts"
            )
            rows = cur.fetchall()
            out: List[StoredAlert] = []
            for r in rows:
                arg_mapping = None
                if r["arg_mapping"]:
                    try:
                        arg_mapping = json.loads(r["arg_mapping"])
                    except Exception:
                        arg_mapping = None
                out.append(
                    StoredAlert(
                        id=r["id"],
                        alert_name=r["alert_name"],
                        audio_asset_id=r["audio_asset_id"],
                        visual_asset_id=r["visual_asset_id"],
                        play_duration=r["play_duration"],
                        fade_inout_time=r["fade_inout_time"],
                        text_template=r["text_template"],
                        arg_mapping=arg_mapping,
                        created_at=r["created_at"],
                    )
                )
            return out
        finally:
            conn.close()

    def get_alert(self, alert_id: str) -> Optional[StoredAlert]:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "SELECT id, alert_name, audio_asset_id, visual_asset_id, play_duration, fade_inout_time, text_template, arg_mapping, created_at FROM alerts WHERE id = ?",
                (alert_id,),
            )
            r = cur.fetchone()
            if not r:
                return None
            arg_mapping = None
            if r["arg_mapping"]:
                try:
                    arg_mapping = json.loads(r["arg_mapping"])
                except Exception:
                    arg_mapping = None
            return StoredAlert(
                id=r["id"],
                alert_name=r["alert_name"],
                audio_asset_id=r["audio_asset_id"],
                visual_asset_id=r["visual_asset_id"],
                play_duration=r["play_duration"],
                fade_inout_time=r["fade_inout_time"],
                text_template=r["text_template"],
                arg_mapping=arg_mapping,
                created_at=r["created_at"],
            )
        finally:
            conn.close()
