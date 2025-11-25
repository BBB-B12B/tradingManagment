"""Wrapper around ccxt Binance for live orders."""

from __future__ import annotations

import ccxt


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str) -> None:
        self.client = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "spot"},
        })

    def submit_market(self, symbol: str, side: str, amount: float) -> dict:
        return self.client.create_order(symbol=symbol, type="market", side=side, amount=amount)
