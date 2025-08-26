from typing import Callable, Optional, Pattern, Dict, Any
import re
import time
import asyncio
import threading

from .trigger_store import TriggerStore, get_trigger_cache


class Trigger:
    def __init__(
        self,
        pattern: str,
        response: Optional[str] = None,
        alert: Optional[dict] = None,
        cooldown_minutes: int = 0,
        trigger_id: Optional[str] = None,
        last_fired: float = 0.0,
    ):
        self.pattern: Pattern[str] = re.compile(pattern)
        self.response = response
        self.alert = alert
        # cooldown expressed in minutes
        self.cooldown_minutes = cooldown_minutes
        self._last_fired = float(last_fired or 0.0)
        self.id = trigger_id

    def matches(self, text: str) -> Optional[re.Match]:
        return self.pattern.search(text)

    def can_fire(self) -> bool:
        # _last_fired stored in seconds since epoch; compare elapsed seconds
        return (time.time() - self._last_fired) >= (self.cooldown_minutes * 60)

    def mark_fired(self) -> None:
        self._last_fired = time.time()


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
        # lock to ensure cache refresh (swap) blocks matching/processing
        self._triggers_lock = threading.Lock()
        self.on_alert: Optional[Callable[[Dict[str, Any]], None]] = None
        # scheduler is lazy-imported to avoid heavy deps at import time
        from .scheduler import Scheduler

        # create scheduler which will call self._send_message_async
        self.scheduler = Scheduler(send_callable=self._send_message_async)

        # persistent trigger storage and cache
        self.trigger_store = TriggerStore()
        # use module-level cache so multiple components share same view
        self._trigger_cache = get_trigger_cache()

        def _on_cache_refresh(trigger_list):
            # Convert StoredTrigger list into compiled Trigger objects
            new: list[Trigger] = []
            for st in trigger_list:
                if st.response_type_id == 1:
                    new.append(
                        Trigger(
                            st.regex_pattern,
                            response=st.response_text,
                            alert=None,
                            cooldown_minutes=st.cooldown_minutes,
                            trigger_id=st.id,
                            last_fired=getattr(st, "last_fired", 0.0),
                        )
                    )
                elif st.response_type_id == 2:
                    alert_payload = {"args": st.arg_mappings} if st.arg_mappings else {}
                    new.append(
                        Trigger(
                            st.regex_pattern,
                            response=None,
                            alert=alert_payload,
                            cooldown_minutes=st.cooldown_minutes,
                            trigger_id=st.id,
                            last_fired=getattr(st, "last_fired", 0.0),
                        )
                    )
            # swap in new triggers while holding the lock so matching is blocked
            with self._triggers_lock:
                self.triggers = new

        # register listener and start periodic refresh while stream is online
        self._trigger_cache.register_listener(_on_cache_refresh)
        # ensure initial population
        try:
            _on_cache_refresh(self._trigger_cache.list_cached_triggers())
        except Exception:
            pass

    def add_trigger(
        self,
        pattern: str,
        response: Optional[str] = None,
        alert: Optional[dict] = None,
        cooldown_minutes: int = 0,
        response_type_id: int | None = None,
        arg_mappings: Optional[Dict[str, Any]] = None,
    ) -> str:
        # determine response_type_id if not provided
        if response_type_id is None:
            response_type_id = 2 if alert is not None else 1

        # persist to store and add to in-memory list
        tid = self.trigger_store.add_trigger(
            regex_pattern=pattern,
            response_type_id=response_type_id,
            response_text=response,
            arg_mappings=arg_mappings,
            cooldown_minutes=cooldown_minutes,
        )

        if response_type_id == 1:
            self.triggers.append(
                Trigger(pattern, response, None, cooldown_minutes, trigger_id=tid)
            )
        else:
            self.triggers.append(
                Trigger(
                    pattern,
                    None,
                    alert or ({"args": arg_mappings} if arg_mappings else {}),
                    cooldown_minutes,
                    trigger_id=tid,
                )
            )
        return tid

    def remove_trigger(self, trigger_id: str) -> bool:
        # remove from DB and in-memory
        ok = self.trigger_store.remove_trigger(trigger_id)
        if ok:
            # reload in-memory triggers from store to keep in sync
            self.triggers.clear()
            for st in self.trigger_store.list_triggers():
                if st.response_type_id == 1:
                    self.triggers.append(
                        Trigger(
                            st.regex_pattern,
                            response=st.response_text,
                            alert=None,
                            cooldown_minutes=st.cooldown_minutes,
                        )
                    )
                elif st.response_type_id == 2:
                    alert_payload = {"args": st.arg_mappings} if st.arg_mappings else {}
                    self.triggers.append(
                        Trigger(
                            st.regex_pattern,
                            response=None,
                            alert=alert_payload,
                            cooldown_minutes=st.cooldown_minutes,
                        )
                    )
        return ok

    async def _handle_message(
        self, author: str, content: str, reply_callable: Callable[[str], asyncio.Future]
    ) -> None:
        # Offload the potentially CPU-bound regex scanning to a thread so we don't
        # block the asyncio event loop when chat moves quickly or there are many
        # configured triggers. Matching is done against precompiled patterns.
        def _find_matching_triggers(content: str):
            out: list[Trigger] = []
            # hold the lock while iterating triggers so refresh can't swap them
            with self._triggers_lock:
                for trig in self.triggers:
                    try:
                        if trig.matches(content) and trig.can_fire():
                            out.append(trig)
                    except Exception:
                        # ignore matching errors per-trigger
                        continue
            return out

        matches = await asyncio.to_thread(_find_matching_triggers, content)

        for trig in matches:
            trig.mark_fired()
            # persist last-fired timestamp if this trigger is persisted
            try:
                if getattr(trig, "id", None):
                    self.trigger_store.update_last_fired(trig.id, trig._last_fired)
            except Exception:
                # best-effort persistence; ignore failures
                pass
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
        self, message: str, interval_minutes: int, enabled: bool = True
    ) -> str:
        return self.scheduler.add(
            message=message, interval_minutes=interval_minutes, enabled=enabled
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
