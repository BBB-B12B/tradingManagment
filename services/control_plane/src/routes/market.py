"""Market data proxy endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from clients.binance_th_client import BinanceTHClient, SUPPORTED_INTERVALS


router = APIRouter(prefix="/market", tags=["market"])
_binance_client = BinanceTHClient()


@router.get("/candles")
async def get_candles(
    pair: str = Query(..., description="Trading pair, e.g. BTC/THB"),
    interval: str = Query("1h", description="Binance interval, e.g. 1h, 4h, 1d"),
    limit: int = Query(120, ge=1, le=1000),
    start_time: Optional[int] = Query(None, description="Start time in ms"),
    end_time: Optional[int] = Query(None, description="End time in ms"),
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
    return {
        "pair": pair.upper(),
        "interval": interval,
        "limit": limit,
        "candles": candles,
    }


__all__ = ["router"]
