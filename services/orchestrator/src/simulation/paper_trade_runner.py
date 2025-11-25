"""Paper trade runner using Binance Testnet to simulate order execution."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import ccxt.async_support as ccxt_async


class PaperTradeRunner:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.client = ccxt_async.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "future", "test": True},
        })

    async def submit(self, order_plan: Dict[str, Any]) -> Dict[str, Any]:
        symbol = order_plan["symbol"].replace("/", "")
        response = await self.client.create_order(
            symbol=symbol,
            type="MARKET",
            side=order_plan["side"],
            amount=order_plan["amount"],
        )
        return response

    async def close(self) -> None:
        await self.client.close()
