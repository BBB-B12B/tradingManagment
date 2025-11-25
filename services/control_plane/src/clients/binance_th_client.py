"""Simple HTTP client for fetching Binance TH kline data."""

from __future__ import annotations

from typing import List, Literal, Optional

import httpx


BINANCE_BASE_URL = "https://api.binance.com"
SUPPORTED_INTERVALS = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
}


class BinanceTHClient:
    """Fetches candles from Binance TH using public REST endpoints."""

    def __init__(self, base_url: str = BINANCE_BASE_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def get_candles(
        self,
        pair: str,
        interval: str = "1h",
        limit: int = 120,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[dict]:
        """Fetch OHLCV candles.

        Args:
            pair: e.g. "BTC/THB"
            interval: Binance interval string (1m, 1h, 1d, etc.)
            limit: number of rows to return (max 1000 per Binance API)
            start_time: optional ms timestamp
            end_time: optional ms timestamp
        """
        symbol = self._normalize_symbol(pair)
        if interval not in SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported interval: {interval}")

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(max(limit, 1), 1000),
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/api/v3/klines", params=params)
            resp.raise_for_status()
            data = resp.json()

        return [self._decorate_row(pair, interval, row) for row in data]

    def _normalize_symbol(self, pair: str) -> str:
        return pair.replace("/", "").upper()

    def _decorate_row(self, pair: str, interval: str, row: List) -> dict:
        open_time, open_, high, low, close, volume, close_time, *_rest = row
        return {
            "pair": pair.upper(),
            "symbol": self._normalize_symbol(pair),
            "interval": interval,
            "open_time": open_time,
            "close_time": close_time,
            "open": float(open_),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume),
        }


__all__ = ["BinanceTHClient", "SUPPORTED_INTERVALS"]
