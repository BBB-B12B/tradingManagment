"""Config synchronization service subscribing to changes from control plane."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict

class ConfigSync:
    def __init__(self, fetcher: Callable[[], Dict[str, Any]]) -> None:
        self.fetcher = fetcher
        self.cache: Dict[str, Any] = {}

    async def run(self, interval: int = 60) -> None:
        while True:
            latest = self.fetcher()
            self.cache.update(latest)
            await asyncio.sleep(interval)
