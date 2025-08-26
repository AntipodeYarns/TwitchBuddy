"""Run a minimal HTTPS listener to handle Twitch OAuth redirect (Authorization Code).

This script starts a FastAPI app on https://127.0.0.1:3883 and exposes `/oauth/callback`.
When Twitch redirects with `?code=...&scope=...`, the script exchanges the code for a token
using the client ID/secret from environment variables and prints the obtained token.

Usage:
  - Generate cert/key: python scripts/generate_selfsigned_cert.py
  - Start listener: python scripts/run_oauth_redirect.py
  - Register https://127.0.0.1:3883/oauth/callback as the redirect URL in the Twitch app
  - Authorize in browser using Twitch OAuth Authorization URL

Note: Browsers may warn about the self-signed cert. Accept the warning for local dev.
"""

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import os
import httpx

app = FastAPI()

CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
REDIRECT_PATH = "/oauth/callback"


@app.get(REDIRECT_PATH)
async def oauth_callback(request: Request):
    params = dict(request.query_params)
    code = params.get("code")
    _state = params.get("state")
    if not code:
        return PlainTextResponse("Missing code", status_code=400)

    token_url = "https://id.twitch.tv/oauth2/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": f"https://127.0.0.1:3883{REDIRECT_PATH}",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data, timeout=10.0)
        resp.raise_for_status()
        token = resp.json()

    # print token server-side and return a short success page
    print("Obtained token:", token)
    return PlainTextResponse("Authorization complete. You can close this window.")


if __name__ == "__main__":
    import uvicorn

    cert = "cert.pem"
    key = "key.pem"
    if not (os.path.exists(cert) and os.path.exists(key)):
        print(
            "Certificate files not found. Run: python scripts/generate_selfsigned_cert.py"
        )
        raise SystemExit(1)

    uvicorn.run(app, host="127.0.0.1", port=3883, ssl_certfile=cert, ssl_keyfile=key)
