from __future__ import annotations

import asyncio
import contextlib
import re
import time
from datetime import UTC, datetime

from sentinel.config import SentinelConfig, TelegramChannel
from sentinel.fetchers.base import BaseFetcher
from sentinel.models import Article

_NUMERIC_CHANNEL_ID = re.compile(r"-?\d+")


class TelegramFetcher(BaseFetcher):
    """Listens to configured Telegram channels for new messages using telethon.

    Unlike other fetchers, Telegram works via a persistent connection:
    1. On startup: connects to Telegram, monitors configured channels
    2. Runs a background listener that buffers incoming messages
    3. On fetch() call: returns and clears the buffer, and retries in the
       background any channel that could not be resolved so far
    """

    def __init__(self, config: SentinelConfig):
        super().__init__(config)
        self.buffer: list[Article] = []
        self.client = None  # TelegramClient, set in start()
        self._running = False
        # Numeric peer id (as in ``message.chat_id``) -> channel config, resolved in start()
        # and, for channels that failed there, by the retry that fetch() schedules.
        self.channels_by_peer: dict[int, TelegramChannel] = {}
        self._unresolved: list[TelegramChannel] = []
        self._new_message_event = None  # telethon.events.NewMessage, set in start()
        self._retry_task: asyncio.Task | None = None
        self._retry_not_before = 0.0  # time.monotonic() value; set from a Telegram flood wait

    @property
    def name(self) -> str:
        return "telegram"

    def is_enabled(self) -> bool:
        return self.config.sources.telegram.enabled

    async def start(self) -> None:
        """Start the Telegram client and message listener."""
        if not self.is_enabled():
            self.logger.info("Telegram fetcher disabled, not starting")
            return

        try:
            from telethon import TelegramClient, events
        except ImportError:
            self.logger.error("telethon not installed; Telegram fetcher cannot start")
            return

        tg_config = self.config.sources.telegram

        self.client = TelegramClient(
            session=tg_config.session_name,
            api_id=tg_config.api_id,
            api_hash=tg_config.api_hash,
        )
        await self.client.start()
        self._new_message_event = events.NewMessage
        self._unresolved = list(tg_config.channels)
        self.channels_by_peer = {}
        self._retry_not_before = 0.0
        # Running from here on, so fetch() retries the pending channels even when the
        # first attempt below raises.
        self._running = True

        await self._resolve_pending(retry=False)
        if not self.channels_by_peer:
            self.logger.error("No Telegram channel could be resolved yet; later fetches retry them in the background")

        self.logger.info(
            "Telegram fetcher started, monitoring %d of %d channels",
            len(self.channels_by_peer),
            len(tg_config.channels),
        )

    async def _on_new_message(self, event) -> None:
        article = self._message_to_article(event.message, self.channels_by_peer)
        if article:
            self.buffer.append(article)

    async def _resolve_pending(self, *, retry: bool) -> None:
        """Resolve every channel not resolved yet and start listening to the ones that resolve.

        Each resolved channel's numeric peer id (the value of ``message.chat_id``) maps
        to its config in ``channels_by_peer``. A channel that cannot be resolved stays
        pending for the next retry, so its messages are dropped until it resolves. A
        Telegram flood wait on one channel delays the next retry by the longest wait
        seen, but the remaining channels are still tried in this attempt: numeric ids
        and session-cached usernames resolve without a request. For a request type that
        is still flood-waited, Telethon sleeps inside the call when the remaining wait is
        at most its ``flood_sleep_threshold`` (60 s by default) and refuses it locally,
        without sending it, only when the wait is longer. So a later uncached lookup in
        the same attempt can take up to that threshold.
        """
        newly_resolved: list[int] = []
        for channel in list(self._unresolved):
            # A numeric channel_id is a peer id already; a string of digits would be
            # read as a phone number.
            target = (
                int(channel.channel_id) if _NUMERIC_CHANNEL_ID.fullmatch(channel.channel_id) else channel.channel_id
            )
            try:
                peer_id = await self.client.get_peer_id(target)
            except Exception as exc:
                log = self.logger.warning if retry else self.logger.error
                log("Cannot resolve Telegram channel %s (%s): %s", channel.name, channel.channel_id, exc)
                flood_wait = getattr(exc, "seconds", None)
                if isinstance(flood_wait, int | float) and flood_wait > 0:
                    self._retry_not_before = max(self._retry_not_before, time.monotonic() + flood_wait)
                continue
            self._unresolved.remove(channel)
            if peer_id in self.channels_by_peer:
                self.logger.error(
                    "Telegram channels %s and %s resolve to the same peer id; keeping %s",
                    self.channels_by_peer[peer_id].name,
                    channel.name,
                    self.channels_by_peer[peer_id].name,
                )
                continue
            self.channels_by_peer[peer_id] = channel
            newly_resolved.append(peer_id)
            if retry:
                self.logger.info("Telegram channel %s (%s) resolved on retry", channel.name, channel.channel_id)

        if not newly_resolved:
            return
        # One more handler for the new peers only: no peer id is in two handlers,
        # and the handlers already registered keep running untouched.
        try:
            self.client.add_event_handler(self._on_new_message, self._new_message_event(chats=newly_resolved))
        except Exception:
            # Not listened to means not resolved: keep these channels for the next retry.
            for peer_id in newly_resolved:
                self._unresolved.append(self.channels_by_peer.pop(peer_id))
            raise

    def _schedule_channel_retry(self) -> None:
        """Start one background attempt to resolve the channels still pending.

        It runs off the fetch path, so a slow lookup (or a flood wait Telethon
        sleeps through) never delays the cycle. At most one attempt runs at a time.
        """
        if not self._running or not self._unresolved or self.client is None or self._new_message_event is None:
            return
        if self._retry_task is not None and not self._retry_task.done():
            return
        if time.monotonic() < self._retry_not_before:
            return
        self._retry_task = asyncio.create_task(self._retry_unresolved())

    async def _retry_unresolved(self) -> None:
        try:
            await self._resolve_pending(retry=True)
        except Exception as exc:
            self.logger.error("Telegram channel retry failed: %s", exc, exc_info=True)

    async def fetch(self) -> list[Article]:
        """Return buffered messages and clear the buffer.

        Also starts the background retry of channels not resolved yet, unless one is
        running or a Telegram flood wait is still in force.
        """
        if not self.is_enabled():
            return []

        self._schedule_channel_retry()
        articles = self.buffer.copy()
        self.buffer.clear()
        return articles

    async def stop(self) -> None:
        """Disconnect from Telegram."""
        self._running = False
        if self._retry_task is not None and not self._retry_task.done():
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as exc:
                self.logger.error("Error disconnecting Telegram client: %s", exc)

    def _message_to_article(self, message, channel_map: dict[int, TelegramChannel]) -> Article | None:
        """Convert a Telegram message to an Article of the channel it was posted in.

        ``channel_map`` is keyed by numeric peer id (see ``_resolve_pending``). A
        message from any other chat is logged and dropped, never attributed to
        another channel.
        """
        try:
            text = message.text or ""
            if not text.strip():
                return None

            channel_config = channel_map.get(message.chat_id)
            if channel_config is None:
                self.logger.warning(
                    "Dropping Telegram message %s from unmonitored chat %s", message.id, message.chat_id
                )
                return None

            # Title: first 200 chars
            title = text[:200]
            # Summary: up to 500 chars
            summary = text[:500]

            # Build URL from channel and message ID
            channel_name = channel_config.channel_id.lstrip("@")
            source_url = f"https://t.me/{channel_name}/{message.id}"

            # Published time from message date
            published_at = message.date
            if published_at and published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            if published_at is None:
                published_at = datetime.now(UTC)

            raw_metadata = {
                "channel_id": channel_config.channel_id,
                "message_id": message.id,
                "views": getattr(message, "views", None),
                "forwards": getattr(message, "forwards", None),
            }

            return Article(
                source_name=channel_config.name,
                source_url=source_url,
                source_type="telegram",
                title=title,
                summary=summary,
                language=channel_config.language,
                published_at=published_at,
                fetched_at=datetime.now(UTC),
                raw_metadata=raw_metadata,
            )

        except Exception as exc:
            self.logger.error("Failed to convert Telegram message: %s", exc)
            return None
