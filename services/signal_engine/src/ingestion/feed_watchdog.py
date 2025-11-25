"""Watchdog monitors candle ingestion latency and emits alerts."""

from __future__ import annotations

import time
from typing import Callable


class FeedWatchdog:
    def __init__(self, max_gap_seconds: int, alert_fn: Callable[[str], None]):
        self.max_gap_seconds = max_gap_seconds
        self.alert_fn = alert_fn
        self._last_timestamp = time.time()

    def heartbeat(self) -> None:
        self._last_timestamp = time.time()

    def check(self) -> None:
        if time.time() - self._last_timestamp > self.max_gap_seconds:
            self.alert_fn("feed_gap_detected")
