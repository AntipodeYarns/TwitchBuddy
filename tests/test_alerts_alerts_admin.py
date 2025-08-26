from fastapi.testclient import TestClient

from twitchbuddy.alerts import create_app


def test_alerts_admin_endpoints():
    app = create_app()
    client = TestClient(app)

    # create prerequisite assets
    a1 = client.post(
        "/admin/assets",
        json={
            "short_name": "sfx",
            "asset_kind": "audio",
            "asset_class": "audio",
            "file_path": "/m/sfx.mp3",
        },
    ).json()["id"]
    v1 = client.post(
        "/admin/assets",
        json={
            "short_name": "gfx",
            "asset_kind": "visual",
            "asset_class": "visual",
            "file_path": "/m/gfx.png",
        },
    ).json()["id"]

    payload = {
        "alert_name": "cheer",
        "audio_asset_id": a1,
        "visual_asset_id": v1,
        "play_duration": "03.00",
        "fade_inout_time": "00.50",
        "text_template": "Thanks {user}",
        "arg_mapping": {"user": "display_name"},
    }

    r = client.post("/admin/alerts", json=payload)
    assert r.status_code == 200
    aid = r.json().get("id")
    assert aid

    r2 = client.get("/admin/alerts")
    assert r2.status_code == 200
    items = r2.json()
    assert any(x["id"] == aid for x in items)

    r3 = client.get(f"/admin/alerts/{aid}")
    assert r3.status_code == 200
    assert r3.json()["alert_name"] == "cheer"

    r4 = client.delete(f"/admin/alerts/{aid}")
    assert r4.status_code == 200
    assert r4.json().get("status") == "deleted"
