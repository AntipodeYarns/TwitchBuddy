import pytest

from twitchbuddy.alerts import BroadcastManager


@pytest.mark.asyncio
async def test_broadcast_manager():
    bm = BroadcastManager()

    class DummyWS:
        def __init__(self):
            self.sent = []

        async def accept(self):
            return

        async def send_text(self, text):
            self.sent.append(text)

    ws1 = DummyWS()
    ws2 = DummyWS()

    await bm.connect(ws1)
    await bm.connect(ws2)

    await bm.broadcast({"text": "hello"})

    assert len(ws1.sent) == 1
    assert len(ws2.sent) == 1
