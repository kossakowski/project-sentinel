from __future__ import annotations

from datetime import datetime, timezone

from sentinel.config import SentinelConfig
from sentinel.fetchers.base import BaseFetcher
from sentinel.models import Article


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
            self.logger.error(
                "telethon not installed; Telegram fetcher cannot start"
            )
            return

        tg_config = self.config.sources.telegram

        self.client = TelegramClient(
            session=tg_config.session_name,
            api_id=tg_config.api_id,
            api_hash=tg_config.api_hash,
        )
        await self.client.start()

        # Build a map of channel_id -> channel config for fast lookup
        channel_ids = [ch.channel_id for ch in tg_config.channels]
        channel_map = {ch.channel_id: ch for ch in tg_config.channels}

        @self.client.on(events.NewMessage(chats=channel_ids))
        async def handler(event):
            article = self._message_to_article(event.message, channel_map)
            if article:
                self.buffer.append(article)

        self._running = True
        self.logger.info(
            "Telegram fetcher started, monitoring %d channels",
            len(channel_ids),
        )

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

    def _message_to_article(self, message, channel_map: dict) -> Article | None:
        """Convert a Telegram message to an Article."""
        try:
            text = message.text or ""
            if not text.strip():
                return None

            # Find the channel config for this message
            chat_id = str(message.chat_id)
            channel_config = None

            for ch_id, ch_cfg in channel_map.items():
                # Match by channel_id (could be @username or numeric ID)
                if str(ch_id) == chat_id or ch_cfg.channel_id == chat_id:
                    channel_config = ch_cfg
                    break

            # Fallback: use first channel if we can't match
            if channel_config is None:
                channel_config = next(iter(channel_map.values()), None)

            if channel_config is None:
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
                published_at = published_at.replace(tzinfo=timezone.utc)
            if published_at is None:
                published_at = datetime.now(timezone.utc)

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
                fetched_at=datetime.now(timezone.utc),
                raw_metadata=raw_metadata,
            )

        except Exception as exc:
            self.logger.error("Failed to convert Telegram message: %s", exc)
            return None
