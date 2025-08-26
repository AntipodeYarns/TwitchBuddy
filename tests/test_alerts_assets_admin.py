from fastapi.testclient import TestClient

from twitchbuddy.alerts import create_app


def test_assets_admin_endpoints():
    app = create_app()
    client = TestClient(app)

    # create asset
    payload = {
        "short_name": "bg_music",
        "asset_kind": "audio",
        "asset_class": "audio",
        "file_path": "/media/bg.mp3",
        "file_type": "mp3",
        "loopable": "yes",
        "media_length": "00:03:00.00",
        "copyright_safe": "yes",
    }
    r = client.post("/admin/assets", json=payload)
    assert r.status_code == 200
    tid = r.json().get("id")
    assert tid

    # list assets
    r2 = client.get("/admin/assets?kind=audio")
    assert r2.status_code == 200
    items = r2.json()
    assert any(x["short_name"] == "bg_music" for x in items)

    # delete asset
    r3 = client.delete(f"/admin/assets/{tid}")
    assert r3.status_code == 200
    assert r3.json().get("status") == "deleted"
