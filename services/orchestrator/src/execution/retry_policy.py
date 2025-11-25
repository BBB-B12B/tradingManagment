"""Retry wrapper for Binance API execution."""

from __future__ import annotations

import time
from typing import Callable


def execute_with_retry(func: Callable[[], dict], retries: int = 3, delay: float = 1.0) -> dict:
    for attempt in range(retries):
        try:
            return func()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
    raise RuntimeError("unreachable")
