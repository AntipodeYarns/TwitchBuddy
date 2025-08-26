import time
from pathlib import Path

from twitchbuddy.trigger_store import TriggerStore, get_trigger_cache


def test_trigger_cache_auto_refresh(tmp_path: Path) -> None:
    # create a dedicated DB path for test isolation
    db_path = tmp_path / "tb_cache.db"

    # seed the DB with one trigger
    store = TriggerStore(db_path=db_path)
    store.add_trigger(regex_pattern=r"ping", response_type_id=1, response_text="pong")

    # get cache for this DB and start auto-refresh with a short interval
    cache = get_trigger_cache(db_path=db_path)

    # start auto-refresh; production uses 1800s (30m) but for tests use 1s
    cache.start_auto_refresh(stream_check=lambda: True, refresh_interval=1)

    # wait a bit longer than the interval so the refresh runs
    time.sleep(1.5)

    try:
        cached = cache.list_cached_triggers()
        assert (
            len(cached) >= 1
        ), "Expected cached triggers to be non-empty after auto-refresh"
    finally:
        cache.stop_auto_refresh()
