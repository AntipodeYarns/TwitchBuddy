# TwitchBuddy

Minimal Python 3.12 workspace for the TwitchBuddy project.

Try it:

```powershell
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; python -V
pip install -e .
pytest -q
```

Developer setup
-----------------

1. Create and activate a Python 3.12 virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install runtime and dev dependencies:

```powershell
pip install -e .
pip install -r requirements-dev.txt
```

3. Install pre-commit hooks (once):

```powershell
pre-commit install
pre-commit run --all-files
```

4. Run the test suite and linters locally:

```powershell
pytest -q
ruff .
mypy --config-file=pyproject.toml
black --check .
```

Twitch developer setup
----------------------

If you plan to use Twitch API features (Helix/EventSub) you need to register an
app at https://dev.twitch.tv/console/apps and set the following environment
variables. Do NOT commit your client secret into the repository — use a local
`.env` file or your OS secret store.

Required environment variables:

```
TWITCH_CLIENT_ID=your-client-id
TWITCH_CLIENT_SECRET=your-client-secret
TWITCH_OAUTH_REDIRECT_URI=https://127.0.0.1:3883
```

Quick token sanity check (requires `.venv` active):

```powershell
# install httpx if not already installed
pip install httpx

# run a quick Python one-liner that uses the helper to fetch an app token
python -c "from twitchbuddy.twitch_api import TwitchAPI; import asyncio; api=TwitchAPI(); asyncio.run(api._acquire_app_token()); print('token ok')"
```

This project includes a `.env.example` with the variables you need to set.

The project also reads `TWITCH_CHANNEL` which is the channel login the bot
should join. For your setup set it to `storygirl` (the login is usually
lowercase even if the display name contains capitals).

Notes
-----
- The repo uses a `src/` layout. Mypy/ruff/black configs live in `pyproject.toml`.
- CI is configured in `.github/workflows/ci.yml` and runs on push/PR.
