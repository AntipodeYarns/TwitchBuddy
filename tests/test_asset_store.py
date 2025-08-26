import os
import tempfile

from twitchbuddy.asset_store import AssetStore


def test_add_list_remove_asset():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        store = AssetStore(db_path=path)
        aid = store.add_asset(
            short_name="intro",
            asset_kind="audio",
            file_path="/media/intro.mp3",
            file_type="mp3",
            loopable="no",
            media_length="00:00:30.00",
            copyright_safe="yes",
        )
        assert isinstance(aid, str)

        assets = store.list_assets()
        assert any(a.id == aid for a in assets)

        # get by short name
        a = store.get_asset_by_short_name("intro")
        assert a is not None and a.short_name == "intro"

        ok = store.remove_asset(aid)
        assert ok
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
