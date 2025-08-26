import threading
import time
import asyncio

from twitchbuddy.twitch_client import ChatClient


def test_matching_blocks_during_cache_swap():
    client = ChatClient()

    # ensure a trigger exists that matches 'hello'
    client.add_trigger(pattern=r"hello", response="Hi!", cooldown_minutes=0)

    # Acquire the client's triggers lock to simulate a cache swap in progress
    lock = client._triggers_lock
    lock.acquire()

    results = []

    async def run_handle():
        async def reply_fn(text: str):
            results.append(text)

        await client._handle_message("user", "hello there", reply_fn)

    # run the handler in a separate thread (it will offload matching to a thread and block)
    t = threading.Thread(target=lambda: asyncio.run(run_handle()))
    t.start()

    # give it a moment to reach the blocked state
    time.sleep(0.2)

    # thread should still be alive because matching is blocked by the lock
    assert t.is_alive(), "Handler thread should be blocked while cache lock is held"

    # release the lock so the handler can proceed
    lock.release()

    t.join(timeout=2.0)
    assert not t.is_alive(), "Handler thread should finish after lock released"
    # allow duplicates (tests may share module-level cache); ensure at least one reply
    assert any(
        r == "Hi!" for r in results
    ), f"Expected at least one reply 'Hi!', got {results}"
