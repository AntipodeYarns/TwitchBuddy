from fastapi.testclient import TestClient

from twitchbuddy.alerts import create_app


def test_admin_triggers_endpoints(tmp_path):
    app = create_app()
    client = TestClient(app)

    # list should return a list
    r = client.get("/admin/triggers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    # create a trigger
    payload = {"regex_pattern": "abc", "response_type_id": 1, "response_text": "hi"}
    r2 = client.post("/admin/triggers", json=payload)
    assert r2.status_code == 200
    body = r2.json()
    assert "id" in body
    tid = body["id"]

    # ensure it's present in list
    r3 = client.get("/admin/triggers")
    ids = [t["id"] for t in r3.json()]
    assert tid in ids

    # delete it
    r4 = client.delete(f"/admin/triggers/{tid}")
    assert r4.status_code == 200
    assert r4.json().get("status") == "deleted"
