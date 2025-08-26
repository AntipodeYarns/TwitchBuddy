We're doing to try to create a Python-based Twitch-Bot that has the following primary functions:

1. Monitor Twitch Chat and apply RegEx pattern matching against incoming chat messages, with each regex pattern having a corresponding response or Alert Trigger. Chat triggers will inject chat responses directly into the channel's Twitch chat.
2. Scheduled broadcast messages that will be emitted to chat on a given schedule.
3. Monitor the Twitch API for incoming Twitch events, such as bit donations, subscriptions, raids and other Twitch events available through the relevant API.
4. Emit Alerts to an HTML Canvas that will be broadcast on localhost:3080 which can be subscribed to by an OBS Browser Source. Alerts will have the following components:
    a. A still graphic, GIF or video file which will be displayed on the canvas.
    b. An audio file which will play when the graphic is displayed.
    c. A text template with options for named arguments, which can be configured using curly braces {args} to specify arguments to the text file which will be replaced by appropriate data provided in ordered comma separated format which map to relevant Twitch API or chat values.
    d. A duration for the alert
    e. A fade-in/fade-out duration for the alert which over-rides the length of any playing media.
5. Provide a GUI for configuring chat responses and alerts with the following tabs:
    a. Twitch Connection Details
    b. Chat trigger configuration
    c. Chat scheduled message configuration
    d. Chat Alert trigger configuration
    e. Twitch API Event alert configuration.
    f. Media bin for audio content.
    g. Media bin for visual content.

The hope is that we can use Python for as much of this functionality as possible. We will use Python 3.12 as our baseline unless there is a dependency requiring a higher version of Python.

At a later date, we hope to capture chat messages to a column-store database for statistical analysis as follows:

1. Track user timeout count
2. Track user deleted message count
3. Track user automod held message count
4. Track number of streams in which the user has chatted.
5. Track number of chat messages sent by the chatter.
6. Provide a list of streams in the configured channel's follow list in which the chatter is banned.

These statistics would then be able to be displayed in an alert box in response to a chat command.

Regarding Python UI - I would like to use the simplest possible UI/UX framework, and am open to recommendations. Electron would be an acceptable fallback if there is no easy to use Python windowed application framework available.

If we need to configure a dynamic hosting site in order to emit alert HTML, FastAPI or a similar lightweight Python Web Server would be preferred, although Node.js would also be acceptable.

Admin HTTP endpoints for trigger management
------------------------------------------

The alerts FastAPI application exposes a small set of admin endpoints to manage chat/alert triggers at runtime. These are:

- GET /admin/triggers — list stored triggers (id, regex_pattern, response_type_id, response_text, arg_mappings, cooldown_minutes)
- POST /admin/triggers — create a trigger. JSON body must include `regex_pattern` (string) and `response_type_id` (int). Optional fields: `response_text`, `arg_mappings` (object), `cooldown_minutes` (int).
- DELETE /admin/triggers/{trigger_id} — remove a trigger by id.

These endpoints are intentionally minimal and intended for operator use behind appropriate authentication in production.

For later (performance, safety, and ops)
--------------------------------------

The following are recommended improvements to address performance, correctness, and production readiness. They are intentionally deferred and listed here for planning:

- Make trigger firing atomic: add a small lock (e.g., threading.Lock) to `Trigger` so `can_fire()` and `mark_fired()` are safe when matching is offloaded to threads.
- Improve matching performance for large trigger sets:
    - Shard triggers by prefix or first-char to reduce candidate sets.
    - For plain substring matches, consider Aho-Corasick or a trie implementation.
    - Benchmark with realistic message rates and trigger counts to choose the right approach.
- Protect admin endpoints with authentication (API key or OAuth) before exposing in production.
- Use Pydantic request/response models for admin endpoints to improve validation and OpenAPI docs.
- Add CI (GitHub Actions) to run black/ruff/mypy/pytest on PRs and main branch.
- Database hardening and concurrency:
    - Use SQLite WAL mode and short-lived connections, or move to server DB (Postgres) for multi-process concurrency.
    - Add simple retry/backoff for transient SQLITE_BUSY.
- Add migrations/versioning for DB schema (Alembic or simple migration tool).
        - Consider separating runtime DB files from repository (add to .gitignore). Use seeded fixtures for tests.


Ad-hoc requirements implemented during development
-------------------------------------------------

During implementation several ad-hoc features and operational requirements were added. The following list records each addition, the rationale, where it was implemented, and current status.

- ClickHouse optional analytics logging
    - What: Optional batched ClickHouse logger for chat and trigger events (batch 50 rows or 15 minutes).
    - Files: `src/twitchbuddy/ch_logging.py`, `clickhouse_ddls.md`.
    - Status: Implemented (guarded import when ClickHouse client unavailable). Includes batching, flush-on-close, and DDL guidance.

- Stream state helper and offline flush semantics
    - What: Track stream online/offline status to control background flush behavior; on shutdown, if stream offline persist buffered events for a configurable grace period and poll stream state every minute.
    - Files: `src/twitchbuddy/stream_state.py`, `src/twitchbuddy/ch_logging.py` (close logic uses stream check).
    - Status: Implemented and tested.

- Timezone-aware datetimes
    - What: Replace naive utcnow() calls with timezone-aware `datetime.now(datetime.UTC)` across the codebase.
    - Files: multiple; fixes applied where naive datetime was used (tests and modules).
    - Status: Completed.

- Trigger cache (in-process) with listener support and auto-refresh
    - What: Cache triggers in-process to avoid DB hits per chat message; supports listener registration for consumers to receive swap notifications and an auto-refresh thread that runs while the stream is online.
    - Files: `src/twitchbuddy/trigger_store.py` (TriggerCache, `get_trigger_cache`), `src/twitchbuddy/twitch_client.py` (consumer wiring and swap lock).
    - Status: Implemented; includes start/stop auto-refresh and notification hooks.

- Cache-swap locking to block matching during refresh
    - What: Ensure cache refresh swaps block trigger-matching to avoid races by adding a short lock around swap operations.
    - Files: `src/twitchbuddy/twitch_client.py` (acquires `self._triggers_lock` while using cached triggers; cache listener also acquires during swap).
    - Status: Implemented and covered by tests.

- Admin UI and endpoints for alerts/assets/triggers/config
    - What: Minimal single-page admin UI to list/create/delete triggers, assets, alerts and to configure Twitch client credentials and admin-auth settings.
    - Files: `web/static/admin.html`, `web/static/admin.js`, `src/twitchbuddy/alerts.py` (admin routes `/admin/*`, `/admin/config`).
    - Status: Implemented; UI served at `/admin`.

- Admin authentication modes (none | API key | Basic)
    - What: Allow operator to choose admin auth mode via UI and persist mode and credentials. Server enforces selected mode via a FastAPI dependency reading env vars `ADMIN_AUTH_MODE`, `ADMIN_API_KEY`, `ADMIN_BASIC_USER`, `ADMIN_BASIC_PASS`.
    - Files: `src/twitchbuddy/alerts.py` (require_admin dependency, config persistence), `web/static/admin.html`, `web/static/admin.js` (UI wiring).
    - Status: Implemented; saving via the UI persists to `twitch_config.json` and sets in-process env vars so changes take effect immediately.

- Admin `/admin/config` expanded to store admin auth settings
    - What: Persist Twitch client config + admin auth settings to `twitch_config.json` next to DB.
    - Files: `src/twitchbuddy/alerts.py` (`get_config`, `set_config`).
    - Status: Implemented (GET masks secrets for display).

- Asset and Alert creation endpoints and UI wiring
    - What: POST endpoints for assets and alerts and corresponding UI create forms (accepts short_name, file_path, associations).
    - Files: `src/twitchbuddy/alerts.py`, `src/twitchbuddy/asset_store.py`, `src/twitchbuddy/alert_store.py`, `web/static/admin.*`.
    - Status: Implemented (basic validation). File upload support remains a recommended follow-up.

- Tests for trigger cache behavior and locking
    - What: Unit tests exercising cache refresh, auto-refresh, and locking behavior to ensure matching is blocked during cache swap.
    - Files: `tests/test_trigger_cache_refresh.py`, `tests/test_trigger_cache_lock.py`, `tests/test_ch_logging.py` (ClickHouse test harness).
    - Status: Implemented and passing locally.

- CI / quality tooling integration (local)
    - What: Project uses `ruff`, `black`, and `mypy` and has pre-commit hooks configured; development ensured code passes these tools locally.
    - Files: various; hooks run during commit.
    - Status: Configured and used; pre-commit auto-formatted several files on commit.

Notes and actionable follow-ups
- Admin authentication: current persistence stores secrets in plaintext in `twitch_config.json` for convenience; consider a secrets store or OS keyring for multi-user systems.
- File uploads: add `/admin/assets/upload` and client-side upload flow to store asset binaries into a media directory and record metadata in the DB.
- Admin UI security: when exposing beyond localhost, add stronger auth (short-lived tokens, OAuth, or integrate with OS auth) and enable HTTPS.
- EventSub & OAuth flows: automate token exchange and EventSub subscription lifecycle in the `twitch_api` module.
- ClickHouse: consider a small integration test harness or a docker-compose config for running a local ClickHouse for CI tests.

This document will be kept in sync with future ad-hoc additions; if you want, I can also:

- Convert the above into a CHANGELOG entry and create a git tag.
- Add a short README section describing how to run locally and how to enable admin auth modes.
