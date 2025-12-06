"""Market data proxy endpoints."""

from __future__ import annotations

import datetime as dt
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query

from clients.binance_th_client import BinanceTHClient, SUPPORTED_INTERVALS
from indicators.action_zone import compute_action_zone
from libs.common.cdc_rules.types import Candle, CDCColor
from libs.common.cdc_rules.pattern_classifier import classify_pattern


router = APIRouter(prefix="/market", tags=["market"])
_binance_client = BinanceTHClient()


@router.get("/last")
async def get_last_price(
    pair: str = Query(..., description="Trading pair, e.g. BTC/THB or BTC/USDT"),
    interval: str = Query("1h", description="Binance interval for reference, e.g. 1h, 4h, 1d"),
) -> dict:
    candles = await _binance_client.get_candles(pair=pair, interval=interval, limit=1)
    if not candles:
        raise HTTPException(status_code=404, detail="No price data")
    return {"pair": pair.upper(), "price": candles[-1]["close"], "interval": interval}


@router.get("/candles")
async def get_candles(
    pair: str = Query(..., description="Trading pair, e.g. BTC/THB"),
    interval: str = Query("1h", description="Binance interval, e.g. 1h, 4h, 1d"),
    limit: int = Query(120, ge=1, le=1000),
    start_time: Optional[int] = Query(None, description="Start time in ms"),
    end_time: Optional[int] = Query(None, description="End time in ms"),
    include_indicators: bool = Query(False, description="Include CDC color and MACD histogram"),
) -> dict:
    if interval not in SUPPORTED_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Unsupported interval: {interval}")

    candles = await _binance_client.get_candles(
        pair=pair,
        interval=interval,
        limit=limit,
        start_time=start_time,
        end_time=end_time,
    )

    # Add CDC Action Zone indicators if requested
    if include_indicators and candles:
        closes = [c["close"] for c in candles]
        zones = compute_action_zone(closes)

        for candle, zone in zip(candles, zones):
            candle["cdc_color"] = zone["cdc_color"]
            candle["action_zone"] = zone["zone"]
            candle["ema_fast"] = zone["ema_fast"]
            candle["ema_slow"] = zone["ema_slow"]
            candle["xprice"] = zone["xprice"]

        # Add W-shape pattern classification for each candle
        # Convert to Candle objects for pattern classification
        candle_objects = []
        for i, c in enumerate(candles):
            ts = dt.datetime.utcfromtimestamp(c["open_time"] / 1000)
            # Determine CDC color from action zone
            zone_color = zones[i]["zone"]
            if zone_color == "green":
                cdc_color = CDCColor.GREEN
            elif zone_color == "red":
                cdc_color = CDCColor.RED
            else:
                cdc_color = None

            candle_objects.append(
                Candle(
                    timestamp=ts,
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    volume=c.get("volume", 0.0),
                    cdc_color=cdc_color,
                )
            )

        # Classify pattern for each candle (using sliding window)
        w_window_bars = 30  # Default window size
        for i in range(len(candles)):
            if i < w_window_bars:
                # Not enough history for pattern classification
                candles[i]["pattern"] = "NONE"
                candles[i]["is_v_shape"] = False
            else:
                # Get candles up to this point
                candles_up_to_i = candle_objects[:i+1]
                pattern_result = classify_pattern(candles_up_to_i, w_window_bars)

                # pattern_result is a RuleResult with metadata containing pattern_type
                if pattern_result.metadata and "pattern_type" in pattern_result.metadata:
                    pattern_type = pattern_result.metadata["pattern_type"]
                    candles[i]["pattern"] = pattern_type
                    candles[i]["is_v_shape"] = pattern_type == "V_SHAPE"
                else:
                    candles[i]["pattern"] = "NONE"
                    candles[i]["is_v_shape"] = False

    return {
        "pair": pair.upper(),
        "interval": interval,
        "limit": limit,
        "candles": candles,
    }


__all__ = ["router"]
