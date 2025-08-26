import os
import tempfile

from twitchbuddy.alert_store import AlertStore
from twitchbuddy.asset_store import AssetStore


def test_add_list_remove_alert():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        asset_store = AssetStore(db_path=path)
        # create sample assets
        audio_id = asset_store.add_asset(
            "beep",
            "audio",
            "/m/beep.mp3",
            file_type="mp3",
            loopable="no",
            copyright_safe="yes",
        )
        visual_id = asset_store.add_asset(
            "flash",
            "visual",
            "/m/flash.png",
            file_type="png",
            loopable="no",
            copyright_safe="yes",
        )

        store = AlertStore(db_path=path)
        aid = store.add_alert(
            alert_name="test",
            audio_asset_id=audio_id,
            visual_asset_id=visual_id,
            play_duration="00:03.00",
            fade_inout_time="00:00.50",
            text_template="Hello {user}",
            arg_mapping={"user": "author"},
        )
        assert isinstance(aid, str)

        alerts = store.list_alerts()
        assert any(a.id == aid for a in alerts)

        got = store.get_alert(aid)
        assert got is not None and got.alert_name == "test"

        ok = store.remove_alert(aid)
        assert ok
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
