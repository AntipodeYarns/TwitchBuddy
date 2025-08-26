from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio
import json
from typing import List
from typing import Dict, Any

from .trigger_store import TriggerStore


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


def create_app() -> FastAPI:
    app = FastAPI()
    bm = BroadcastManager()
    app.state.bm = bm
    # trigger store for admin operations
    store = TriggerStore()
    app.state.trigger_store = store
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
