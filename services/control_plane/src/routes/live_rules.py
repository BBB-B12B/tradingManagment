"""Live rule evaluation using Binance market data."""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from httpx import HTTPStatusError

from clients.binance_th_client import BinanceTHClient
from libs.common.cdc_rules import evaluate_all_rules
from libs.common.cdc_rules.types import Candle, CDCColor
from routes.config import _db as config_store


router = APIRouter(prefix="/rules/live", tags=["rules"])
_market_client = BinanceTHClient()

DEFAULT_LTF_LIMIT = 200
LTF_TO_HTF = {
    "15m": "1h",
    "30m": "4h",
    "1h": "1d",
    "4h": "1d",
    "1d": "1w",
}


def _ema(values: List[float], period: int) -> List[float]:
    alpha = 2 / (period + 1)
    ema_values: List[float] = []
    ema = values[0]
    ema_values.append(ema)
    for price in values[1:]:
        ema = alpha * price + (1 - alpha) * ema
        ema_values.append(ema)
    return ema_values


def _macd_histogram(closes: List[float]) -> List[float]:
    if len(closes) < 2:
        return [0.0 for _ in closes]
    ema_fast = _ema(closes, 12)
    ema_slow = _ema(closes, 26)
    macd_line = [fast - slow for fast, slow in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, 9)
    return [macd - signal for macd, signal in zip(macd_line, signal_line)]


def _decorate_candles(raw_rows: List[dict]) -> List[Candle]:
    closes = [row["close"] for row in raw_rows]
    hist = _macd_histogram(closes)

    candles: List[Candle] = []
    for row, hist_value in zip(raw_rows, hist):
        ts = dt.datetime.utcfromtimestamp(row["open_time"] / 1000)
        color = CDCColor.GREEN if hist_value >= 0 else CDCColor.RED
        candles.append(
            Candle(
                timestamp=ts,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                cdc_color=color,
            )
        )
    return candles


async def _evaluate_pair(
    pair: str,
    timeframe: Optional[str],
    htf_timeframe: Optional[str],
    limit: int,
) -> dict:
    cfg = config_store.get(pair.upper())
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Config not found for pair {pair}")

    ltf_interval = timeframe or cfg.timeframe
    htf_interval = htf_timeframe or LTF_TO_HTF.get(ltf_interval, "1d")

    try:
        ltf_rows = await _market_client.get_candles(pair=pair, interval=ltf_interval, limit=limit)
        htf_rows = await _market_client.get_candles(pair=pair, interval=htf_interval, limit=min(limit, 120))
    except HTTPStatusError as exc:
        content = exc.response.text
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch Binance data for {pair} ({ltf_interval}/{htf_interval}). Response: {content}",
        ) from exc

    ltf_candles = _decorate_candles(ltf_rows)
    htf_candles = _decorate_candles(htf_rows)
    macd_hist = _macd_histogram([row["close"] for row in ltf_rows])

    result = evaluate_all_rules(
        candles_ltf=ltf_candles,
        candles_htf=htf_candles,
        macd_histogram=macd_hist,
        params=cfg.rule_params,
        enable_w_shape_filter=cfg.enable_w_shape_filter,
        enable_leading_signal=cfg.enable_leading_signal,
    )

    return {
        "pair": pair.upper(),
        "ltf_timeframe": ltf_interval,
        "htf_timeframe": htf_interval,
        "candles_used": len(ltf_candles),
        "result": {
            "summary": result.summary,
            "rule_1": {"passed": result.rule_1_cdc_green.passed, "reason": result.rule_1_cdc_green.reason},
            "rule_2": {"passed": result.rule_2_leading_red.passed, "reason": result.rule_2_leading_red.reason},
            "rule_3": {"passed": result.rule_3_leading_signal.passed, "reason": result.rule_3_leading_signal.reason},
            "rule_4": {"passed": result.rule_4_pattern.passed, "reason": result.rule_4_pattern.reason},
        },
    }


@router.get("/evaluate")
async def evaluate_live_rules(
    pair: str = Query(..., description="Trading pair, e.g., BTC/USDT"),
    timeframe: Optional[str] = Query(None, description="Lower timeframe (defaults to config timeframe)"),
    htf_timeframe: Optional[str] = Query(None, description="Higher timeframe (defaults to mapping)"),
    limit: int = Query(DEFAULT_LTF_LIMIT, ge=30, le=500),
) -> dict:
    return await _evaluate_pair(pair, timeframe, htf_timeframe, limit)


@router.get("/evaluate/all")
async def evaluate_all_configs(
    timeframe: Optional[str] = Query(None, description="Override lower timeframe for all pairs"),
    limit: int = Query(DEFAULT_LTF_LIMIT, ge=30, le=500),
) -> dict:
    if not config_store:
        raise HTTPException(status_code=404, detail="No configurations defined")

    summaries = []
    for pair in list(config_store.keys()):
        try:
            result = await _evaluate_pair(pair, timeframe, None, limit)
            summaries.append(result)
        except HTTPException as exc:
            summaries.append({"pair": pair, "error": exc.detail})
    return {"count": len(summaries), "results": summaries}


__all__ = ["router"]
