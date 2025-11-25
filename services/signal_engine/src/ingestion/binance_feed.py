"""Binance feed ingestion supporting historical + live candles with metadata snapshots."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any, AsyncIterator, Dict, List

import ccxt.async_support as ccxt_async


class BinanceFeed:
    def __init__(self, api_key: str | None = None, api_secret: str | None = None):
        self.client = ccxt_async.binance({
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "options": {"defaultType": "spot"},
        })

    async def fetch_historical(
        self, symbol: str, timeframe: str, since: int, limit: int = 500
    ) -> List[Dict[str, Any]]:
        candles = await self.client.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        return [self._decorate(symbol, timeframe, candle) for candle in candles]

    async def stream_live(
        self, symbol: str, timeframe: str, poll_interval: int = 60
    ) -> AsyncIterator[Dict[str, Any]]:
        while True:
            now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
            candles = await self.fetch_historical(symbol, timeframe, since=now - 2 * 60 * 60 * 1000, limit=2)
            if candles:
                yield candles[-1]
            await asyncio.sleep(poll_interval)

    def _decorate(self, symbol: str, timeframe: str, candle: List[Any]) -> Dict[str, Any]:
        open_time, open_, high, low, close, volume = candle
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": open_time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "metadata": {
                "source": "binance",
                "timezone": "UTC",
                "hash": hash((symbol, timeframe, open_time, close)),
            },
        }

    async def close(self) -> None:
        await self.client.close()
