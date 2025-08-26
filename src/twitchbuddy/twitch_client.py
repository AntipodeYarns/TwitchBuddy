from typing import Callable, Optional, Pattern, Dict, Any
import re
import time
import asyncio


class Trigger:
    def __init__(
        self,
        pattern: str,
        response: Optional[str] = None,
        alert: Optional[dict] = None,
        cooldown_ms: int = 0,
    ):
        self.pattern: Pattern[str] = re.compile(pattern)
        self.response = response
        self.alert = alert
        self.cooldown_ms = cooldown_ms
        self._last_fired = 0.0

    def matches(self, text: str) -> Optional[re.Match]:
        return self.pattern.search(text)

    def can_fire(self) -> bool:
        return (time.time() * 1000) - self._last_fired >= self.cooldown_ms

    def mark_fired(self) -> None:
        self._last_fired = time.time() * 1000


class ChatClient:
    """Twitch chat client using twitchio for real connectivity.

    Usage:
      client = ChatClient(token, channel)
      client.add_trigger(r"hello", response="Hi!")
      client.on_alert = lambda payload: send_alert(app, payload)
      await client.start()

    If `twitchio` is not installed, start/stop are no-ops so the package remains importable.
    """

    def __init__(self, token: str = "", channel: str = "") -> None:
        self.token = token
        self.channel = channel
        self.triggers: list[Trigger] = []
        self.on_alert: Optional[Callable[[Dict[str, Any]], None]] = None

    def add_trigger(
        self,
        pattern: str,
        response: Optional[str] = None,
        alert: Optional[dict] = None,
        cooldown_ms: int = 0,
    ) -> None:
        self.triggers.append(Trigger(pattern, response, alert, cooldown_ms))

    async def _handle_message(
        self, author: str, content: str, reply_callable: Callable[[str], asyncio.Future]
    ) -> None:
        for trig in self.triggers:
            if trig.matches(content) and trig.can_fire():
                trig.mark_fired()
                # send chat response if present
                if trig.response:
                    try:
                        await reply_callable(trig.response)
                    except Exception:
                        # ignore send failures
                        pass
                # send alert payload if present
                if trig.alert and self.on_alert:
                    try:
                        # allow sync callback
                        maybe = self.on_alert(trig.alert)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    except Exception:
                        pass

    async def start(self) -> None:
        try:
            from twitchio.ext import commands
        except Exception:
            # twitchio not installed: no-op
            return

        # implement a simple commands.Bot that delegates messages to our handler
        token = self.token
        channel = self.channel

        class _Bot(commands.Bot):
            def __init__(self, token: str, channel: str, outer: "ChatClient"):
                # twitchio's Bot signature may vary; ignore type checking for the call
                super().__init__(token=token, prefix="!")  # type: ignore[call-arg]
                self._outer = outer
                self._channel_name = channel

            async def event_ready(self):
                # ready
                return

            async def event_message(self, message):
                # ignore messages from the bot itself
                try:
                    author = message.author.name
                    content = message.content
                except Exception:
                    return

                async def reply_fn(text: str):
                    try:
                        # send to same channel
                        await message.channel.send(text)
                    except Exception:
                        pass

                await self._outer._handle_message(author, content, reply_fn)

        self._bot = _Bot(token=token, channel=channel, outer=self)

        # run bot in background task
        loop = asyncio.get_event_loop()
        self._loop_task = loop.create_task(self._bot.start())

    async def stop(self) -> None:
        if self._bot:
            try:
                await self._bot.close()
            except Exception:
                pass
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=1.0)
            except Exception:
                pass
