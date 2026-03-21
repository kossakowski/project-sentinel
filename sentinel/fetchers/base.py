import logging
from abc import ABC, abstractmethod

from sentinel.config import SentinelConfig
from sentinel.models import Article


class BaseFetcher(ABC):
    """Abstract base class that all fetchers inherit from."""

    def __init__(self, config: SentinelConfig):
        self.config = config
        self.logger = logging.getLogger(f"sentinel.fetcher.{self.name}")

    @property
    @abstractmethod
    def name(self) -> str:
        """Fetcher identifier, e.g. 'rss', 'gdelt'."""

    @abstractmethod
    async def fetch(self) -> list[Article]:
        """Fetch articles from the source. Returns empty list on failure."""

    def is_enabled(self) -> bool:
        """Check if this fetcher is enabled in config."""
        raise NotImplementedError("Subclasses must implement is_enabled()")
