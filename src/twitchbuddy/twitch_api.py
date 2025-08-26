from __future__ import annotations

import asyncio
import os
import time
from typing import Callable, Optional


class TwitchAPI:
    """Minimal helper for Twitch Helix interactions.

    Responsibilities implemented here:
    - Acquire an app access token (client credentials) and refresh it when expiring.
    - Provide a small convenience `get_helix` helper for simple GET requests.

    Notes:
    - This module intentionally reads credentials from environment variables when
      they are not provided to the constructor. Do NOT commit secrets into the
      repository. Use environment variables or a secrets manager.
    - EventSub (webhook or socket delivery) is out-of-scope for this change and
      left as a future implementation.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        # Prefer explicit args, otherwise fall back to environment variables.
        self.client_id = client_id or os.getenv("TWITCH_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("TWITCH_CLIENT_SECRET", "")

        # token state
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

        # optional event callback
        self._on_event: Optional[Callable[[dict], None]] = None

    def on_event(self, callback: Callable[[dict], None]) -> None:
        self._on_event = callback

    async def _acquire_app_token(self) -> None:
        """Acquire an app access token using the client credentials flow.

        This method uses `httpx` if available; if not, it will fall back to
        `requests` executed in a thread.
        """
        if not (self.client_id and self.client_secret):
            raise RuntimeError("TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET must be set")

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }

        url = "https://id.twitch.tv/oauth2/token"

        # Prefer async httpx
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, data=data)
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:  # fallback to requests in a thread
            if isinstance(exc, ImportError):
                # httpx not installed; use requests synchronously in a thread
                import requests

                def _sync_post():
                    r = requests.post(url, data=data, timeout=10.0)
                    r.raise_for_status()
                    return r.json()

                payload = await asyncio.to_thread(_sync_post)
            else:
                # propagate other httpx errors
                raise

        # payload contains access_token and expires_in on success
        token = payload.get("access_token")
        expires_in = int(payload.get("expires_in", 0))
        if not token:
            raise RuntimeError(f"failed to acquire Twitch token: {payload}")

        # apply a small clock skew buffer
        self._access_token = token
        self._token_expiry = time.time() + max(0, expires_in - 30)

    async def _ensure_token(self) -> None:
        if not self._access_token or time.time() >= self._token_expiry:
            await self._acquire_app_token()

    async def get_helix(self, path: str, params: dict | None = None) -> dict:
        """Perform a GET request against the Helix API.

        Example: await api.get_helix('users', {'login':'some_channel'})
        """
        await self._ensure_token()
        headers = {
            k: v
            for k, v in {
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {self._access_token}",
            }.items()
            if v is not None
        }

        url = f"https://api.twitch.tv/helix/{path.lstrip('/') }"

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            # Fallback to requests sync in a thread if httpx is not present
            if isinstance(exc, ImportError):
                import requests

                def _sync_get():
                    r = requests.get(url, params=params, headers=headers, timeout=10.0)
                    r.raise_for_status()
                    return r.json()

                return await asyncio.to_thread(_sync_get)
            raise

    async def get_user_by_login(self, login: str) -> dict | None:
        """Return the first user object for a login name or None if not found.

        This is a convenience helper that calls the Helix `/users` endpoint.
        """
        if not login:
            return None

        res = await self.get_helix("users", {"login": login})
        if not isinstance(res, dict):
            return None

        data = res.get("data") or []
        if not data:
            return None
        return data[0]

    async def start(self) -> None:
        """Placeholder for EventSub or long-running subscriptions.

        Implementing EventSub requires a publicly reachable callback (webhook) or
        a socket-based delivery approach. For local development use ngrok or a
        relay and implement the EventSub subscription workflow here.
        """
        # no-op for now
        return

    async def stop(self) -> None:
        # no-op for now
        return

    # --- EventSub helpers -------------------------------------------------
    async def subscribe_eventsub(
        self, type: str, version: str, condition: dict, transport: dict
    ) -> dict:
        """Create an EventSub subscription via Helix API.

        transport example (webhook):
          {"method":"webhook", "callback":"https://your-callback", "secret":"<secret>"}

        Returns the Helix response as a dict.
        """
        await self._ensure_token()
        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        body = {
            "type": type,
            "version": version,
            "condition": condition,
            "transport": transport,
        }
        headers = {
            k: v
            for k, v in {
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }.items()
            if v is not None
        }

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            if isinstance(exc, ImportError):
                import requests

                def _sync_post():
                    r = requests.post(url, json=body, headers=headers, timeout=10.0)
                    r.raise_for_status()
                    return r.json()

                return await asyncio.to_thread(_sync_post)
            raise

    async def unsubscribe_eventsub(self, subscription_id: str) -> dict:
        await self._ensure_token()
        url = f"https://api.twitch.tv/helix/eventsub/subscriptions?id={subscription_id}"
        headers = {
            k: v
            for k, v in {
                "Client-Id": self.client_id,
                "Authorization": f"Bearer {self._access_token}",
            }.items()
            if v is not None
        }
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.delete(url, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            if isinstance(exc, ImportError):
                import requests

                def _sync_delete():
                    r = requests.delete(url, headers=headers, timeout=10.0)
                    r.raise_for_status()
                    return r.json()

                return await asyncio.to_thread(_sync_delete)
            raise

    def verify_eventsub_signature(
        self, message_id: str, timestamp: str, body_bytes: bytes, signature: str
    ) -> bool:
        """Verify the Twitch EventSub HMAC-SHA256 signature header.

        Twitch sends header `Twitch-Eventsub-Message-Signature: sha256=...`
        where the HMAC is computed over message_id + timestamp + body using
        the subscription secret (client secret or a separate transport secret).
        """
        # signature looks like: "sha256=..."
        if not signature or not signature.startswith("sha256="):
            return False
        sig_hex = signature.split("=", 1)[1]

        secret = self.client_secret
        if not secret:
            # cannot verify without a secret
            return False

        import hmac
        import hashlib

        mac = hmac.new(secret.encode("utf-8"), digestmod=hashlib.sha256)
        mac.update(message_id.encode("utf-8"))
        mac.update(timestamp.encode("utf-8"))
        mac.update(body_bytes)
        expected = mac.hexdigest()
        return hmac.compare_digest(expected, sig_hex)
