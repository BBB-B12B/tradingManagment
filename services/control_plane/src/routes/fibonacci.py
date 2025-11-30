"""
Fibonacci Retracement/Extension API endpoint.

Provides Elliott Wave Fibonacci analysis for chart visualization.
"""

from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from httpx import HTTPStatusError

from clients.binance_th_client import BinanceTHClient
from indicators.fibonacci import get_fibonacci_analysis
from indicators.action_zone import compute_action_zone
from routes.config import _db as config_store

router = APIRouter(prefix="/fibonacci", tags=["fibonacci"])

_market_client = BinanceTHClient()


@router.get("")
async def get_fibonacci_levels(
    pair: str = Query(..., description="Trading pair, e.g., BTC/USDT"),
    timeframe: Optional[str] = Query(None, description="Timeframe (defaults to config timeframe)"),
    limit: int = Query(240, ge=50, le=1000, description="Number of candles to analyze"),
) -> Dict[str, Any]:
    """
    Calculate Fibonacci retracement and extension levels for a trading pair.

    Wave 1-2 Retracement:
    - 0% (Swing High)
    - 61.8%
    - 78.6% (Wave 2 ideal zone start)
    - 88.7% (Wave 2 ideal zone end)
    - 94.2%
    - 100% (Swing Low)

    Wave 3 Extension:
    - 0% (Wave 2 Low)
    - 38.2%
    - 61.8%
    - 100% (Wave 1 High)
    - 161.8% (Primary target)
    """
    # Get config for pair
    cfg = config_store.get(pair.upper())
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Config not found for pair {pair}")

    interval = timeframe or cfg.timeframe

    # Fetch candle data
    try:
        raw_candles = await _market_client.get_candles(
            pair=pair,
            interval=interval,
            limit=limit,
        )
    except (HTTPStatusError, ValueError) as exc:
        response = getattr(exc, "response", None)
        extra = f": {response.text}" if response is not None else f": {exc}"
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch Binance data for {pair} ({interval}){extra}",
        ) from exc

    if not raw_candles:
        raise HTTPException(status_code=400, detail="No candle data available")

    # Add EMA indicators (needed for bear zone detection)
    closes = [c["close"] for c in raw_candles]
    zones = compute_action_zone(closes)

    for candle, zone in zip(raw_candles, zones):
        candle["ema_fast"] = zone["ema_fast"]
        candle["ema_slow"] = zone["ema_slow"]

    # Run Fibonacci analysis
    analysis = get_fibonacci_analysis(raw_candles)

    return {
        "pair": pair.upper(),
        "timeframe": interval,
        "candles_analyzed": len(raw_candles),
        **analysis,
    }


__all__ = ["router"]
