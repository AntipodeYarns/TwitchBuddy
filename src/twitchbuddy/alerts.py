from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    Depends,
    Header,
)
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
from .ch_logging import get_logger


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

    import os

    import base64

    def _set_admin_env_from_payload(cfg: dict) -> None:
        """Helper to set relevant ADMIN_* env vars from provided config dict.

        We set in-process environment variables so checks take effect immediately.
        Persisted JSON also contains the values so they survive restarts.
        """
        mode = cfg.get("admin_auth_mode") or os.environ.get("ADMIN_AUTH_MODE")
        if mode is not None:
            os.environ["ADMIN_AUTH_MODE"] = str(mode)
        # API key
        api_key = cfg.get("admin_api_key")
        if api_key is not None:
            os.environ["ADMIN_API_KEY"] = str(api_key)
        # Basic creds
        basic_user = cfg.get("admin_basic_user")
        basic_pass = cfg.get("admin_basic_pass")
        if basic_user is not None:
            os.environ["ADMIN_BASIC_USER"] = str(basic_user)
        if basic_pass is not None:
            os.environ["ADMIN_BASIC_PASS"] = str(basic_pass)

    async def require_admin(
        x_admin_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        """FastAPI dependency to guard admin API endpoints.

        Behavior controlled by ADMIN_AUTH_MODE env var (none|api_key|basic).
        - none (or unset): no auth performed.
        - api_key: expects X-ADMIN-KEY header to match ADMIN_API_KEY env var.
        - basic: expects HTTP Basic Authorization header matching ADMIN_BASIC_USER/ADMIN_BASIC_PASS.
        """
        mode = os.environ.get("ADMIN_AUTH_MODE", "none")
        mode = (mode or "none").lower()
        if mode in ("", "none"):
            return
        if mode == "api_key":
            expected = os.environ.get("ADMIN_API_KEY")
            if not expected:
                # if no key set, treat as disabled
                return
            if x_admin_key != expected:
                raise HTTPException(status_code=401, detail="Unauthorized")
            return
        if mode == "basic":
            exp_user = os.environ.get("ADMIN_BASIC_USER")
            exp_pass = os.environ.get("ADMIN_BASIC_PASS")
            if not exp_user or not exp_pass:
                return
            if not authorization or not authorization.startswith("Basic "):
                raise HTTPException(status_code=401, detail="Unauthorized")
            try:
                b64 = authorization.split(None, 1)[1]
                decoded = base64.b64decode(b64).decode("utf-8")
                user, pwd = decoded.split(":", 1)
            except Exception:
                raise HTTPException(status_code=401, detail="Unauthorized")
            if user != exp_user or pwd != exp_pass:
                raise HTTPException(status_code=401, detail="Unauthorized")
            return

    @app.get("/")
    async def index():
        return HTMLResponse(open("web/static/alert.html", "r", encoding="utf-8").read())

    @app.get("/admin")
    async def admin_index():
        return HTMLResponse(open("web/static/admin.html", "r", encoding="utf-8").read())

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
        # log to ClickHouse if available
        try:
            logger = get_logger()
            # if payload contains user info and trigger name, log chat event
            user = alert.get("user") if isinstance(alert, dict) else None
            trigger_name = (
                alert.get("trigger_name") if isinstance(alert, dict) else None
            )
            if user:
                logger.log_chat(
                    channel="",
                    username=user,
                    fired=bool(trigger_name),
                    name=trigger_name,
                )
            if trigger_name:
                logger.log_trigger_event(
                    channel="", trigger_name=trigger_name, trigger_type="alert"
                )
        except Exception:
            pass
        return {"status": "ok"}

    # --- admin trigger management -------------------------------------------------
    @app.get("/admin/triggers")
    async def list_triggers(dep=Depends(require_admin)):
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
    async def create_trigger(payload: Dict[str, Any], dep=Depends(require_admin)):
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
        # notify cache to refresh immediately while stream is running
        try:
            from .trigger_store import get_trigger_cache

            cache = get_trigger_cache(db_path=db_path_obj)
            cache.notify_change()
        except Exception:
            pass
        return {"id": tid}

    @app.delete("/admin/triggers/{trigger_id}")
    async def delete_trigger(trigger_id: str, dep=Depends(require_admin)):
        ok = app.state.trigger_store.remove_trigger(trigger_id)
        if not ok:
            raise HTTPException(status_code=404, detail="trigger not found")
        # notify cache to refresh immediately
        try:
            from .trigger_store import get_trigger_cache

            cache = get_trigger_cache(db_path=db_path_obj)
            cache.notify_change()
        except Exception:
            pass
        return {"status": "deleted"}

    # --- admin asset management --------------------------------------------------
    @app.get("/admin/assets")
    async def list_assets(kind: str | None = None, dep=Depends(require_admin)):
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
    async def create_asset(payload: Dict[str, Any], dep=Depends(require_admin)):
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
    async def delete_asset(identifier: str, dep=Depends(require_admin)):
        ok = app.state.asset_store.remove_asset(identifier)
        if not ok:
            raise HTTPException(status_code=404, detail="asset not found")
        return {"status": "deleted"}

    # --- admin config (Twitch credentials, channel details) -------------------
    @app.get("/admin/config")
    async def get_config(dep=Depends(require_admin)):
        """Return stored config from a JSON file next to the DB or repo root.

        Fields: client_id, client_secret (masked), channel, redirect_uri
        """
        import json

        from pathlib import Path

        # config file lives next to DB if db_path_obj provided, else repo CWD
        cfg_path = (
            (db_path_obj.parent / "twitch_config.json")
            if db_path_obj is not None
            else Path.cwd() / "twitch_config.json"
        )
        if not cfg_path.exists():
            return {}
        try:
            with cfg_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            # mask secret for safe display
            if "client_secret" in data and data["client_secret"]:
                data["client_secret"] = "****"
            # mask admin basic password
            if "admin_basic_pass" in data and data["admin_basic_pass"]:
                data["admin_basic_pass"] = "****"
            # don't return the real API key if present (optional)
            if "admin_api_key" in data and data["admin_api_key"]:
                # only expose placeholder
                data["admin_api_key"] = data["admin_api_key"][:4] + "****"
            return data
        except Exception:
            return {}

    @app.post("/admin/config")
    async def set_config(payload: Dict[str, Any], dep=Depends(require_admin)):
        """Persist provided config to JSON. Expected keys: client_id, client_secret, channel, redirect_uri."""
        import json

        from pathlib import Path

        cfg = {
            "client_id": payload.get("client_id"),
            "client_secret": payload.get("client_secret"),
            "channel": payload.get("channel"),
            "redirect_uri": payload.get("redirect_uri"),
            # admin auth settings
            "admin_auth_mode": payload.get("admin_auth_mode"),
            "admin_api_key": payload.get("admin_api_key"),
            "admin_basic_user": payload.get("admin_basic_user"),
            "admin_basic_pass": payload.get("admin_basic_pass"),
        }
        cfg_path = (
            (db_path_obj.parent / "twitch_config.json")
            if db_path_obj is not None
            else Path.cwd() / "twitch_config.json"
        )
        try:
            with cfg_path.open("w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
            # set envs so the running process immediately adopts the new admin auth
            try:
                _set_admin_env_from_payload(cfg)
            except Exception:
                pass
            return {"status": "ok"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # --- admin alert management --------------------------------------------------
    @app.get("/admin/alerts")
    async def list_alerts(dep=Depends(require_admin)):
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
    async def create_alert(payload: Dict[str, Any], dep=Depends(require_admin)):
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
    async def get_alert(alert_id: str, dep=Depends(require_admin)):
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
    async def delete_alert(alert_id: str, dep=Depends(require_admin)):
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
