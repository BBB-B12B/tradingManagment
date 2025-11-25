"""Captures configuration latency/success metrics."""

from __future__ import annotations

import time
from typing import Dict


class ConfigMetrics:
    def __init__(self):
        self.events: list[Dict] = []

    def record(self, duration_seconds: float, success: bool) -> None:
        self.events.append({"duration": duration_seconds, "success": success, "ts": time.time()})
