from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio
import json
from typing import List
from typing import Dict, Any

from .trigger_store import TriggerStore
from .asset_store import AssetStore
from .alert_store import AlertStore
from .config import Config
from .scheduler import Scheduler


class BroadcastManager:
    """Simple broadcast manager for connected WebSocket clients."""

    def __init__(self) -> None:
        self.active: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, message: dict) -> None:
        text = json.dumps(message)
        async with self.lock:
            to_remove: List[WebSocket] = []
            for ws in list(self.active):
                try:
                    await ws.send_text(text)
                except Exception:
                    to_remove.append(ws)
            for ws in to_remove:
                if ws in self.active:
                    self.active.remove(ws)


def create_app(db_path: str | None = None, config: Config | None = None) -> FastAPI:
    """Create the FastAPI app for TwitchBuddy.

    Priority for DB path: explicit db_path arg > Config.db_path > env override > default.
    When running under pytest we create a temporary DB to isolate tests.
    """

    # normalize config
    cfg = config or Config.from_env()

    # pick an effective DB path: explicit arg > config > env/test temp > default
    effective_db_path = db_path or (str(cfg.db_path) if cfg.db_path else None)
    if not effective_db_path:
        import os

        # pytest sets PYTEST_CURRENT_TEST in the environment during runs;
        # create a temp DB file for test isolation when present
        if os.environ.get("PYTEST_CURRENT_TEST"):
            import tempfile

            tmp = tempfile.NamedTemporaryFile(
                prefix="twitchbuddy-test-", suffix=".db", delete=False
            )
            effective_db_path = tmp.name

    # instantiate stores (stores expect Path | None)
    from pathlib import Path

    db_path_obj = Path(effective_db_path) if effective_db_path is not None else None

    trigger_store = TriggerStore(db_path=db_path_obj)
    asset_store = AssetStore(db_path=db_path_obj)
    alert_store = AlertStore(db_path=db_path_obj)

    # broadcast manager must exist before the scheduler so we can pass a
    # send_callable that schedules broadcasts to connected websockets.
    bm = BroadcastManager()

    async def _send_from_scheduler(message: str) -> None:
        # scheduler messages are simple strings; wrap into a dict for clients
        await bm.broadcast({"type": "scheduled", "message": message})

    scheduler = Scheduler(send_callable=_send_from_scheduler, db_path=db_path_obj)

    app = FastAPI()
    # keep scheduler on app.state so it can be controlled and to avoid linter
    # complaints about an unused local variable.
    app.state.scheduler = scheduler
    app.state.bm = bm
    app.state.trigger_store = trigger_store
    app.state.asset_store = asset_store
    app.state.alert_store = alert_store
    # serve static files from web/static
    app.mount("/static", StaticFiles(directory="web/static"), name="static")

    @app.get("/")
    async def index():
        return HTMLResponse(open("web/static/alert.html", "r", encoding="utf-8").read())

    @app.websocket("/ws/alerts")
    async def ws_alerts(ws: WebSocket):
        await bm.connect(ws)
        try:
            while True:
                # keep connection open; clients may send ping/pong messages
                await ws.receive_text()
        except WebSocketDisconnect:
            await bm.disconnect(ws)

    @app.post("/trigger")
    async def trigger(alert: dict):
        """HTTP demo hook to trigger an alert payload to connected clients."""
        await bm.broadcast(alert)
        return {"status": "ok"}

    # --- admin trigger management -------------------------------------------------
    @app.get("/admin/triggers")
    async def list_triggers():
        """Return all stored triggers."""
        ts = app.state.trigger_store.list_triggers()
        # serialize StoredTrigger dataclass to dict
        out = []
        for t in ts:
            out.append(
                {
                    "id": t.id,
                    "regex_pattern": t.regex_pattern,
                    "response_type_id": t.response_type_id,
                    "response_text": t.response_text,
                    "arg_mappings": t.arg_mappings,
                    "cooldown_minutes": t.cooldown_minutes,
                }
            )
        return out

    @app.post("/admin/triggers")
    async def create_trigger(payload: Dict[str, Any]):
        """Create a trigger.

        Expected JSON:
          {"regex_pattern": str, "response_type_id": int, "response_text": str|null, "arg_mappings": dict|null, "cooldown_minutes": int}
        Returns: {"id": <trigger_id>}
        """
        regex = payload.get("regex_pattern")
        rtid = payload.get("response_type_id")
        if not regex or not rtid:
            raise HTTPException(
                status_code=400,
                detail="regex_pattern and response_type_id are required",
            )
        tid = app.state.trigger_store.add_trigger(
            regex_pattern=regex,
            response_type_id=int(rtid),
            response_text=payload.get("response_text"),
            arg_mappings=payload.get("arg_mappings"),
            cooldown_minutes=int(payload.get("cooldown_minutes") or 0),
        )
        return {"id": tid}

    @app.delete("/admin/triggers/{trigger_id}")
    async def delete_trigger(trigger_id: str):
        ok = app.state.trigger_store.remove_trigger(trigger_id)
        if not ok:
            raise HTTPException(status_code=404, detail="trigger not found")
        return {"status": "deleted"}

    # --- admin asset management --------------------------------------------------
    @app.get("/admin/assets")
    async def list_assets(kind: str | None = None):
        """List assets; optional query param `kind` (audio|visual)."""
        if kind is not None and kind not in ("audio", "visual"):
            raise HTTPException(
                status_code=400, detail="kind must be 'audio' or 'visual'"
            )
        assets = app.state.asset_store.list_assets(kind=kind)
        return [
            {
                "id": a.id,
                "short_name": a.short_name,
                "asset_kind": a.asset_kind,
                "asset_class": a.asset_class,
                "file_path": a.file_path,
                "file_type": a.file_type,
                "loopable": a.loopable,
                "media_length": a.media_length,
                "copyright_safe": a.copyright_safe,
                "created_at": a.created_at,
            }
            for a in assets
        ]

    @app.post("/admin/assets")
    async def create_asset(payload: Dict[str, Any]):
        """Create an asset. Required: short_name, asset_kind, file_path. Optional: file_type, loopable (yes/no), media_length, copyright_safe (yes/no)."""
        short_name = payload.get("short_name")
        asset_kind = payload.get("asset_kind")
        file_path = payload.get("file_path")
        if not short_name or not asset_kind or not file_path:
            raise HTTPException(
                status_code=400,
                detail="short_name, asset_kind and file_path are required",
            )
        try:
            aid = app.state.asset_store.add_asset(
                short_name=short_name,
                asset_kind=asset_kind,
                asset_class=payload.get("asset_class"),
                file_path=file_path,
                file_type=payload.get("file_type"),
                loopable=payload.get("loopable", "no"),
                media_length=payload.get("media_length"),
                copyright_safe=payload.get("copyright_safe", "no"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"id": aid}

    @app.delete("/admin/assets/{identifier}")
    async def delete_asset(identifier: str):
        ok = app.state.asset_store.remove_asset(identifier)
        if not ok:
            raise HTTPException(status_code=404, detail="asset not found")
        return {"status": "deleted"}

    # --- admin alert management --------------------------------------------------
    @app.get("/admin/alerts")
    async def list_alerts():
        alerts = app.state.alert_store.list_alerts()
        out = []
        for a in alerts:
            out.append(
                {
                    "id": a.id,
                    "alert_name": a.alert_name,
                    "audio_asset_id": a.audio_asset_id,
                    "visual_asset_id": a.visual_asset_id,
                    "play_duration": a.play_duration,
                    "fade_inout_time": a.fade_inout_time,
                    "text_template": a.text_template,
                    "arg_mapping": a.arg_mapping,
                    "created_at": a.created_at,
                }
            )
        return out

    @app.post("/admin/alerts")
    async def create_alert(payload: Dict[str, Any]):
        required = payload.get("alert_name")
        if not required:
            raise HTTPException(status_code=400, detail="alert_name is required")
        try:
            aid = app.state.alert_store.add_alert(
                alert_name=payload["alert_name"],
                audio_asset_id=payload.get("audio_asset_id"),
                visual_asset_id=payload.get("visual_asset_id"),
                play_duration=payload.get("play_duration"),
                fade_inout_time=payload.get("fade_inout_time"),
                text_template=payload.get("text_template"),
                arg_mapping=payload.get("arg_mapping"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"id": aid}

    @app.get("/admin/alerts/{alert_id}")
    async def get_alert(alert_id: str):
        a = app.state.alert_store.get_alert(alert_id)
        if not a:
            raise HTTPException(status_code=404, detail="alert not found")
        return {
            "id": a.id,
            "alert_name": a.alert_name,
            "audio_asset_id": a.audio_asset_id,
            "visual_asset_id": a.visual_asset_id,
            "play_duration": a.play_duration,
            "fade_inout_time": a.fade_inout_time,
            "text_template": a.text_template,
            "arg_mapping": a.arg_mapping,
            "created_at": a.created_at,
        }

    @app.delete("/admin/alerts/{alert_id}")
    async def delete_alert(alert_id: str):
        ok = app.state.alert_store.remove_alert(alert_id)
        if not ok:
            raise HTTPException(status_code=404, detail="alert not found")
        return {"status": "deleted"}

    @app.post("/eventsub/webhook")
    async def eventsub_webhook(request):
        """Receive EventSub webhook verification and notifications.

        This endpoint implements the lightweight verification flow required by
        Twitch. It expects headers and a JSON body. On verification (challenge)
        it must echo the challenge.
        """
        # Read raw body for signature verification
        body = await request.body()
        headers = request.headers
        message_id = headers.get("Twitch-Eventsub-Message-Id", "")
        timestamp = headers.get("Twitch-Eventsub-Message-Timestamp", "")
        msg_type = headers.get("Twitch-Eventsub-Message-Type", "")
        signature = headers.get("Twitch-Eventsub-Message-Signature", "")

        # Deferred import to avoid hard runtime dependency in tests
        try:
            from .twitch_api import TwitchAPI
        except Exception:
            TwitchAPI = None

        # attempt verification if possible
        verified = True
        if TwitchAPI is not None:
            api = TwitchAPI()
            verified = api.verify_eventsub_signature(
                message_id, timestamp, body, signature
            )

        import json as _json

        payload = _json.loads(body.decode("utf-8") or "{}")

        # handle verification challenge
        if msg_type == "webhook_callback_verification":
            # on verification, return the challenge string exactly
            challenge = payload.get("challenge")
            return {"challenge": challenge}

        # handle revocation messages
        if msg_type == "revocation":
            # broadcast the revocation notice for operator awareness
            await bm.broadcast({"type": "eventsub.revoked", "payload": payload})
            return {"status": "revoked"}

        # handle notification messages (deliver event to connected clients)
        if msg_type == "notification":
            if not verified:
                return {"status": "forbidden"}, 403
            event = payload.get("event")
            await bm.broadcast({"type": "eventsub.notification", "event": event})
            return {"status": "ok"}

        return {"status": "ignored"}

    return app


def send_alert(app: FastAPI, payload: dict) -> None:
    """Helper to schedule a broadcast from synchronous code.

    This schedules the broadcast on the app event loop.
    """
    loop = asyncio.get_event_loop()
    # schedule coroutine
    loop.create_task(app.state.bm.broadcast(payload))
