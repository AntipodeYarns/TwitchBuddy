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
        # scheduler is lazy-imported to avoid heavy deps at import time
        from .scheduler import Scheduler

        # create scheduler which will call self._send_message_async
        self.scheduler = Scheduler(send_callable=self._send_message_async)

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

    async def _send_message_async(self, message: str) -> None:
        """Async send helper used by the scheduler. Sends to chat if bot is available."""
        if not getattr(self, "_bot", None):
            return
        try:
            # attempt to send to configured channel name
            chan = getattr(self._bot, "_channel_name", self.channel)
            # twitchio message send: channel object vs name; try attribute then fallback
            try:
                # if bot has a connected channel mapping, prefer that
                await self._bot.get_channel(chan).send(message)  # type: ignore[attr-defined]
            except Exception:
                # fallback: try to use bot's send or global send
                try:
                    await self._bot._ws.send_privmsg(chan, message)  # type: ignore[attr-defined]
                except Exception:
                    # give up silently
                    pass
        except Exception:
            pass

    def send_message(self, message: str) -> None:
        """Public sync method to send a message; schedules an asyncio call."""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self._send_message_async(message))
        else:
            loop.run_until_complete(self._send_message_async(message))

    # Schedule management wrappers
    def add_schedule(
        self, message: str, interval_seconds: int, enabled: bool = True
    ) -> str:
        return self.scheduler.add(
            message=message, interval_seconds=interval_seconds, enabled=enabled
        )

    def remove_schedule(self, schedule_id: str) -> bool:
        return self.scheduler.remove(schedule_id)

    def list_schedules(self) -> Dict[str, Dict[str, Any]]:
        return self.scheduler.list()

    def start_schedules(self) -> None:
        self.scheduler.start()

    def stop_schedules(self) -> None:
        self.scheduler.stop()

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
