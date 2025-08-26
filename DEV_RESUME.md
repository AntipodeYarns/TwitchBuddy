# Developer Resume / How to resume work on this project

This file describes the minimal steps to restore the development environment and the project state so you can pick up where you left off.

1) Clone and set up

```powershell
git clone https://github.com/AntipodeYarns/TwitchBuddy.git
cd TwitchBuddy
python -m venv .venv
. .\.venv\Scripts\Activate
pip install -r requirements.txt
```

2) Restore runtime state (optional)

- Backups live in the `backups/` folder if you created any earlier. Unzip or copy DB files and `twitch_config.json` into the repo root.

3) Start the app (development)

```powershell
# Use the bundled runner
python .\run_alerts.py
# or run with uvicorn factory for auto-reload
uvicorn --factory "src.twitchbuddy.alerts:create_app" --host 127.0.0.1 --port 3080 --reload
```

4) Admin UI and auth

- Admin UI: http://127.0.0.1:3080/admin
- Admin auth modes: none, api_key, basic
- To set admin creds persistently: use the Admin UI -> Twitch Config tab -> Save
- To set credentials in the session before startup, create a `.env` file in repo root with:

```powershell
ADMIN_AUTH_MODE=api_key
ADMIN_API_KEY=your-secret-key
ADMIN_BASIC_USER=admin
ADMIN_BASIC_PASS=s3cret
```

5) Tests & quality checks

```powershell
# run tests
pytest -q
# run linters
ruff check .
# type check
mypy
```

6) Backups

- A helper script is available at `scripts/backup.ps1` to snapshot DBs and the `twitch_config.json` file into `backups/<timestamp>/` and compress the snapshot.

7) Notes & security

- Do not commit `.env` or any files with secrets.
- `twitch_config.json` currently stores credentials in plaintext; treat this file as sensitive.
- Before exposing admin UI beyond localhost, enable auth mode and use secure storage for secrets.

# TO DO:
+ Fix UI - look at migrating to Electron app.
+ Add nice-to-haves to UI
    ++ Select Assets from ComboBoxes with autocomplete
    ++ Add file-picker to asset entry tab
    ++ Add filters on Asset bin page (Audio vs Visual, loopable, filetype, etc)
    ++ Add Twitch/App config forms with options for endpoint security, caching, etc.
    ++ Add JS resolver to RegEx pattern to parse tokens like ${user}, ${game}, ${Clip_URL}, eval${...} etc.
+ Add DB Backup/Restore functionality to UI with file-picker, etc.
+ Add functionality allowing {url-player} tokens to be included in alerts for stuff like clip players, tiktok videos, music videos (for !sr requests) etc.
