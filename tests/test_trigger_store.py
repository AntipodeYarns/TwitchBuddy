import os
import tempfile

from twitchbuddy.trigger_store import TriggerStore


def test_add_list_remove_trigger():
    # use a temp file for isolation
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        store = TriggerStore(db_path=path)

        tid = store.add_trigger(
            regex_pattern=r"hello",
            response_type_id=1,
            response_text="Hi",
            arg_mappings={"who": "user"},
            cooldown_minutes=0,
        )
        assert isinstance(tid, str)

        ts = store.list_triggers()
        assert any(t.id == tid for t in ts)

        ok = store.remove_trigger(tid)
        assert ok is True

        ts2 = store.list_triggers()
        assert not any(t.id == tid for t in ts2)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def test_invalid_arg_mappings_does_not_crash():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # manually write an invalid JSON into arg_mappings then ensure list_triggers handles it
        store = TriggerStore(db_path=path)
        tid = store.add_trigger("a", 1, response_text=None, arg_mappings=None)
        # corrupt the DB row directly
        import sqlite3

        conn = sqlite3.connect(path)
        conn.execute(
            "UPDATE triggers SET arg_mappings=? WHERE id=?", ("not-a-json", tid)
        )
        conn.commit()
        conn.close()

        ts = store.list_triggers()
        # should not raise and should return a list
        assert isinstance(ts, list)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
