from __future__ import annotations

import re
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
    3. On fetch() call: returns and clears the buffer
    """

    def __init__(self, config: SentinelConfig):
        super().__init__(config)
        self.buffer: list[Article] = []
        self.client = None  # TelegramClient, set in start()
        self._running = False
        # Numeric peer id (as in ``message.chat_id``) -> channel config, resolved in start().
        self.channels_by_peer: dict[int, TelegramChannel] = {}

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

        channel_map = await self._resolve_channels(tg_config.channels)
        self.channels_by_peer = channel_map
        if not channel_map:
            self.logger.error("No Telegram channel could be resolved; the listener is not started")
            return

        @self.client.on(events.NewMessage(chats=list(channel_map)))
        async def handler(event):
            article = self._message_to_article(event.message, channel_map)
            if article:
                self.buffer.append(article)

        self._running = True
        self.logger.info(
            "Telegram fetcher started, monitoring %d of %d channels",
            len(channel_map),
            len(tg_config.channels),
        )

    async def _resolve_channels(self, channels: list[TelegramChannel]) -> dict[int, TelegramChannel]:
        """Map each channel's numeric peer id (the value of ``message.chat_id``) to its config.

        A channel that cannot be resolved is logged and left out, so its messages are dropped.
        """
        channel_map: dict[int, TelegramChannel] = {}
        for channel in channels:
            # A numeric channel_id is a peer id already; a string of digits would be
            # read as a phone number.
            target = (
                int(channel.channel_id) if _NUMERIC_CHANNEL_ID.fullmatch(channel.channel_id) else channel.channel_id
            )
            try:
                peer_id = await self.client.get_peer_id(target)
            except Exception as exc:
                self.logger.error("Cannot resolve Telegram channel %s (%s): %s", channel.name, channel.channel_id, exc)
                continue
            if peer_id in channel_map:
                self.logger.error(
                    "Telegram channels %s and %s resolve to the same peer id; keeping %s",
                    channel_map[peer_id].name,
                    channel.name,
                    channel_map[peer_id].name,
                )
                continue
            channel_map[peer_id] = channel
        return channel_map

    async def fetch(self) -> list[Article]:
        """Return buffered messages and clear buffer."""
        if not self.is_enabled():
            return []

        articles = self.buffer.copy()
        self.buffer.clear()
        return articles

    async def stop(self) -> None:
        """Disconnect from Telegram."""
        if self.client:
            try:
                await self.client.disconnect()
            except Exception as exc:
                self.logger.error("Error disconnecting Telegram client: %s", exc)
        self._running = False

    def _message_to_article(self, message, channel_map: dict[int, TelegramChannel]) -> Article | None:
        """Convert a Telegram message to an Article of the channel it was posted in.

        ``channel_map`` is keyed by numeric peer id (see ``_resolve_channels``). A
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
