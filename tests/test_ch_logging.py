import time
from datetime import datetime, UTC
from twitchbuddy.ch_logging import BatchedClickHouseLogger
from twitchbuddy.stream_state import set_stream_online, is_stream_online


class FakeClient:
    def __init__(self):
        self.rows = []

    def execute(self, query, rows=None):
        # record rows for assertions
        if rows is not None:
            self.rows.extend(rows)


def test_batched_logger_offline_online(tmp_path):
    fake = FakeClient()

    # ensure channel offline initially
    channel = "testchan"
    set_stream_online(channel, False)

    # create logger with small batch_size and short grace_period for test
    logger = BatchedClickHouseLogger(
        client=fake,
        database=None,
        batch_size=3,
        batch_time=60,
        stream_check=lambda: is_stream_online(channel),
        grace_period=5,
        poll_interval=1,
    )

    # push a few messages
    for i in range(2):
        logger.log_chat(
            channel=channel,
            username=f"user{i}",
            fired=False,
            name=None,
            ts=datetime.now(UTC),
        )

    # close should see stream offline and wait (but our stream_check lambda above is wrong intentionally)
    # Now set stream online after a short delay in background
    def bring_online():
        time.sleep(2)
        set_stream_online(channel, True)

    import threading

    t = threading.Thread(target=bring_online)
    t.start()

    # close should block until stream is reported online (or grace_period elapses)
    logger.close(timeout=10)
    t.join()

    # fake client should have received the 2 rows (flushed on close)
    assert len(fake.rows) >= 2
